"""
Celery 任务定义
"""
import logging
import uuid

from celery import Celery

from app.config import settings

logger = logging.getLogger(__name__)

celery_app = Celery(
    "evo_data_worker",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=True,
)


@celery_app.task(name="validate_dataset", bind=True, max_retries=3)
def validate_dataset_task(self, upload_id: str, description: str = None, tags: str = None):
    """异步校验上传的数据集格式"""
    from app.database import SessionLocal
    from app.datasets.validator import FormatVersion, validate_dataset
    from app.models import (
        Contribution,
        Dataset,
        DatasetVersion,
        Upload,
        UploadStatus,
        UserLevel,
    )

    db = SessionLocal()
    try:
        upload = db.query(Upload).filter(Upload.id == upload_id).first()
        if not upload:
            logger.error(f"Upload {upload_id} not found")
            return

        # 更新状态为校验中
        upload.status = UploadStatus.validating
        db.commit()

        # 执行校验
        result = validate_dataset(upload.oss_path)

        if result.passed:
            # 将格式版本字符串映射到枚举
            version_map = {
                FormatVersion.V21: DatasetVersion.v2_1,
                FormatVersion.V30: DatasetVersion.v3_0,
            }
            detected = version_map.get(result.version, DatasetVersion.unknown)
            upload.detected_version = detected

            # 创建或更新 Dataset 记录
            info = result.info
            dataset = Dataset(
                owner_id=upload.user_id,
                name=upload.dataset_name or f"dataset-{upload_id[:8]}",
                description=description or info.get("description", ""),
                tags=tags,
                version=detected,
                oss_path=upload.oss_path,
                total_episodes=info.get("total_episodes"),
                total_frames=info.get("total_frames"),
                is_public=False,   # 默认不公开，需用户手动设置
            )
            db.add(dataset)
            db.flush()

            upload.dataset_id = dataset.id
            upload.status = UploadStatus.passed

            # 创建 Contribution 记录
            contribution = Contribution(
                user_id=upload.user_id,
                dataset_id=dataset.id,
                upload_id=upload.id,
                status=UploadStatus.passed,
            )
            db.add(contribution)

            # 更新用户等级
            user = upload.user
            if user and user.level == UserLevel.normal:
                user.level = UserLevel.contributor
                user.rank += 10

            db.commit()
            logger.info(f"Upload {upload_id} validated successfully, dataset {dataset.id}")

            # 触发预览生成任务
            generate_preview_task.delay(str(dataset.id))

        else:
            upload.status = UploadStatus.failed
            upload.error_message = "; ".join(result.errors)
            db.commit()
            logger.warning(f"Upload {upload_id} validation failed: {result.errors}")

    except Exception as e:
        logger.exception(f"Validation task failed for upload {upload_id}: {e}")
        try:
            upload = db.query(Upload).filter(Upload.id == upload_id).first()
            if upload:
                upload.status = UploadStatus.failed
                upload.error_message = f"内部错误: {str(e)}"
                db.commit()
        except Exception:
            pass
        raise self.retry(exc=e, countdown=60)
    finally:
        db.close()


@celery_app.task(name="generate_preview", bind=True, max_retries=2)
def generate_preview_task(self, dataset_id: str):
    """
    为数据集生成预览数据（episode_0 的帧和轨迹 JSON），写入 OSS previews/ 目录
    """
    import io
    import json as json_lib
    import tempfile

    from app.database import SessionLocal
    from app.models import Dataset

    db = SessionLocal()
    try:
        dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
        if not dataset or not dataset.oss_path:
            return

        import oss2
        from app.config import settings as cfg

        auth = oss2.Auth(cfg.OSS_ACCESS_KEY_ID, cfg.OSS_ACCESS_KEY_SECRET)
        bucket = oss2.Bucket(auth, cfg.OSS_ENDPOINT, cfg.OSS_BUCKET_NAME)
        prefix = dataset.oss_path.rstrip("/") + "/"

        # 读取 info.json
        info_obj = bucket.get_object(prefix + "meta/info.json")
        info = json_lib.loads(info_obj.read())

        # 找到 episode_0 的 parquet 文件
        ep0_key = None
        for obj in oss2.ObjectIterator(bucket, prefix=prefix + "data/"):
            if "episode_000000.parquet" in obj.key or "episode_0.parquet" in obj.key:
                ep0_key = obj.key
                break

        if not ep0_key:
            logger.warning(f"No episode_0 parquet found for dataset {dataset_id}")
            return

        # 读取 parquet
        try:
            import hyparquet_py as hp  # 尝试使用纯 Python 实现
        except ImportError:
            try:
                import pandas as pd
                import pyarrow.parquet as pq
            except ImportError:
                logger.warning("No parquet library available for preview generation")
                return

        ep0_data = bucket.get_object(ep0_key).read()

        try:
            import pandas as pd
            import pyarrow.parquet as pq
            buf = io.BytesIO(ep0_data)
            table = pq.read_table(buf)
            df = table.to_pandas()
        except Exception as e:
            logger.warning(f"Failed to read parquet for preview: {e}")
            return

        # 提取轨迹数据（取前 200 帧避免过大）
        MAX_FRAMES = 200
        trajectory_rows = []
        for _, row in df.head(MAX_FRAMES).iterrows():
            record: dict = {"timestamp": float(row.get("timestamp", 0))}
            for col in df.columns:
                val = row[col]
                if hasattr(val, "tolist"):
                    record[col] = val.tolist()
                elif hasattr(val, "item"):
                    record[col] = val.item()
                else:
                    try:
                        record[col] = float(val)
                    except Exception:
                        pass
            trajectory_rows.append(record)

        trajectory_json = json_lib.dumps(trajectory_rows)
        preview_prefix = f"previews/{dataset_id}/episode_0/"

        # 写入 trajectory.json
        bucket.put_object(preview_prefix + "trajectory.json", trajectory_json.encode())

        # 写入 meta_preview.json
        meta_preview = {
            "dataset_id": dataset_id,
            "episode_index": 0,
            "fps": info.get("fps", 30),
            "total_frames": len(df),
            "task_instruction": None,
            "features": info.get("features", {}),
        }
        bucket.put_object(
            preview_prefix + "meta_preview.json",
            json_lib.dumps(meta_preview).encode(),
        )

        # 更新数据集预览状态
        dataset.has_preview = True
        dataset.preview_path = preview_prefix
        db.commit()

        logger.info(f"Preview generated for dataset {dataset_id}")

    except Exception as e:
        logger.exception(f"Preview generation failed for dataset {dataset_id}: {e}")
        raise self.retry(exc=e, countdown=120)
    finally:
        db.close()
