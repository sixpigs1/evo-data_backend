"""
Celery 任务定义
"""
import json
import logging
import uuid

from celery import Celery

from app.config import settings

logger = logging.getLogger(__name__)


def _robot_from_tags(tags_json: str = None) -> str:
    """从 JSON tags 字符串中提取 robot_type，用于同步 robot 列"""
    if not tags_json:
        return None
    try:
        return json.loads(tags_json).get("robot_type")
    except (json.JSONDecodeError, TypeError):
        return None

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
def validate_dataset_task(self, upload_id: str, description: str = None, tags: str = None, is_public: bool = False):
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
                robot=_robot_from_tags(tags),   # 从 tags JSON 同步 robot 列
                version=detected,
                oss_path=upload.oss_path,
                total_episodes=info.get("total_episodes"),
                total_frames=info.get("total_frames"),
                is_public=is_public,   # 使用上传时用户的设置
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
    为数据集生成预览数据：
    - episode_0 轨迹 JSON（来自 parquet）
    - thumbnail.jpg（来自 episode_0 视频第一帧，使用 ffmpeg）
    写入 OSS previews/{dataset_id}/ 目录
    """
    import io
    import json as json_lib
    import subprocess
    import tempfile
    import os

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
        upload_prefix = dataset.oss_path.rstrip("/") + "/"

        # ── 自动探测数据集根目录 ────────────────────────────────────────────────
        all_keys = [obj.key for obj in oss2.ObjectIterator(bucket, prefix=upload_prefix)]
        info_candidates = [k for k in all_keys if k.endswith("meta/info.json")]
        if not info_candidates:
            logger.warning(f"No meta/info.json found under {upload_prefix}, skipping preview")
            return
        info_key = min(info_candidates, key=lambda k: k.count("/"))
        prefix = info_key[: -len("meta/info.json")]  # 数据集根，含末尾 /
        logger.info(f"Preview: 数据集根目录 = {prefix}")

        # 读取 info.json
        info_obj = bucket.get_object(prefix + "meta/info.json")
        info = json_lib.loads(info_obj.read())

        preview_prefix = f"previews/{dataset_id}/"
        generated_thumbnail = False
        generated_trajectory = False

        # ── 1. 提取视频第一帧作为缩略图 ────────────────────────────────────────
        # 搜索 videos/ 目录下的 episode_000000.mp4
        video_keys = [
            k for k in all_keys
            if k.startswith(prefix + "videos/") and "episode_000000" in k and k.endswith(".mp4")
        ]
        if not video_keys:
            # 也搜索 episode_0.mp4（兼容）
            video_keys = [
                k for k in all_keys
                if k.startswith(prefix + "videos/") and k.endswith(".mp4")
            ]

        if video_keys:
            video_key = video_keys[0]
            logger.info(f"Preview: 使用视频文件 {video_key}")
            try:
                with tempfile.TemporaryDirectory() as tmpdir:
                    video_path = os.path.join(tmpdir, "episode_0.mp4")
                    thumbnail_path = os.path.join(tmpdir, "thumbnail.jpg")

                    # 从 OSS 下载视频
                    bucket.get_object_to_file(video_key, video_path)

                    # 用 ffmpeg 提取第一帧
                    result = subprocess.run(
                        [
                            "ffmpeg", "-y",
                            "-i", video_path,
                            "-vframes", "1",
                            "-q:v", "3",
                            "-vf", "scale=640:-1",
                            thumbnail_path,
                        ],
                        capture_output=True,
                        timeout=60,
                    )
                    if result.returncode == 0 and os.path.exists(thumbnail_path):
                        with open(thumbnail_path, "rb") as f:
                            thumbnail_data = f.read()
                        bucket.put_object(
                            preview_prefix + "thumbnail.jpg",
                            thumbnail_data,
                            headers={"Content-Type": "image/jpeg"},
                        )
                        dataset.thumbnail_path = preview_prefix + "thumbnail.jpg"
                        generated_thumbnail = True
                        logger.info(f"Preview: 缩略图已生成 ({len(thumbnail_data)} bytes)")
                    else:
                        logger.warning(f"ffmpeg failed: {result.stderr.decode()[:500]}")
            except Exception as e:
                logger.warning(f"Preview: 视频帧提取失败: {e}")
        else:
            logger.info(f"Preview: 未找到视频文件，跳过缩略图生成")

        # ── 2. 提取 episode_0 轨迹数据（来自 parquet）─────────────────────────
        ep0_key = None
        for obj in oss2.ObjectIterator(bucket, prefix=prefix + "data/"):
            if "episode_000000.parquet" in obj.key or "episode_0.parquet" in obj.key:
                ep0_key = obj.key
                break

        if ep0_key:
            try:
                import pandas as pd
                import pyarrow.parquet as pq

                ep0_data = bucket.get_object(ep0_key).read()
                buf = io.BytesIO(ep0_data)
                table = pq.read_table(buf)
                df = table.to_pandas()

                # 提取前 200 帧（排除图像列，避免 JSON 过大）
                MAX_FRAMES = 200
                image_cols = [c for c in df.columns if "image" in c.lower() or "pixel" in c.lower()]
                df_clean = df.drop(columns=image_cols, errors="ignore")

                trajectory_rows = []
                for _, row in df_clean.head(MAX_FRAMES).iterrows():
                    record: dict = {}
                    for col in df_clean.columns:
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
                bucket.put_object(
                    preview_prefix + "trajectory.json",
                    trajectory_json.encode(),
                    headers={"Content-Type": "application/json"},
                )

                # meta_preview.json
                meta_preview = {
                    "dataset_id": dataset_id,
                    "episode_index": 0,
                    "fps": info.get("fps", 30),
                    "total_frames": len(df),
                    "features": {
                        k: v for k, v in info.get("features", {}).items()
                        if k not in image_cols
                    },
                }
                bucket.put_object(
                    preview_prefix + "meta_preview.json",
                    json_lib.dumps(meta_preview).encode(),
                    headers={"Content-Type": "application/json"},
                )
                generated_trajectory = True
                logger.info(f"Preview: 轨迹数据已生成 ({len(trajectory_rows)} frames)")
            except ImportError:
                logger.warning("pandas/pyarrow 未安装，跳过轨迹生成")
            except Exception as e:
                logger.warning(f"Preview: 轨迹提取失败: {e}")
        else:
            logger.warning(f"No episode_0 parquet found for dataset {dataset_id}")

        # ── 3. 更新数据集预览状态 ──────────────────────────────────────────────
        if generated_thumbnail or generated_trajectory:
            dataset.has_preview = True
            dataset.preview_path = preview_prefix
            db.commit()
            logger.info(f"Preview generated for dataset {dataset_id}: thumbnail={generated_thumbnail}, trajectory={generated_trajectory}")
        else:
            logger.warning(f"Preview: 没有生成任何预览内容，跳过状态更新")

    except Exception as e:
        logger.exception(f"Preview generation failed for dataset {dataset_id}: {e}")
        raise self.retry(exc=e, countdown=120)
    finally:
        db.close()
