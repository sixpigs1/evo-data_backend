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

            info = result.info

            # ── 复用或新建 Dataset 记录（避免重复验证产生多个 dataset_id）──────
            dataset = None
            if upload.dataset_id:
                dataset = db.query(Dataset).filter(Dataset.id == upload.dataset_id).first()

            if dataset:
                # 更新已有记录（保持 id、is_public、tags、thumbnail_path 不变）
                dataset.version = detected
                dataset.oss_path = upload.oss_path
                dataset.total_episodes = info.get("total_episodes")
                dataset.total_frames = info.get("total_frames")
                dataset.name = upload.dataset_name or dataset.name
                if description:
                    dataset.description = description
                if tags is not None:
                    dataset.tags = tags
                    dataset.robot = _robot_from_tags(tags)
                logger.info(f"Upload {upload_id}: 复用已有 dataset {dataset.id}")
            else:
                # 新建 Dataset 记录
                dataset = Dataset(
                    owner_id=upload.user_id,
                    name=upload.dataset_name or f"dataset-{upload_id[:8]}",
                    description=description or info.get("description", ""),
                    tags=tags,
                    robot=_robot_from_tags(tags),
                    version=detected,
                    oss_path=upload.oss_path,
                    total_episodes=info.get("total_episodes"),
                    total_frames=info.get("total_frames"),
                    is_public=is_public,
                )
                db.add(dataset)
                db.flush()
                upload.dataset_id = dataset.id
                logger.info(f"Upload {upload_id}: 新建 dataset {dataset.id}")

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
    为数据集生成预览数据（episode_0）：
    - previews/{id}/{cam}.mp4       — episode_0 视频片段（ffmpeg 裁剪）
    - previews/{id}/thumbnail.jpg   — 第一帧缩略图
    - previews/{id}/trajectory.json — 前 300 帧轨迹数据
    - previews/{id}/meta_preview.json — 元信息 + video_keys
    """
    import io
    import json as json_lib
    import re
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
            logger.warning(f"No meta/info.json under {upload_prefix}, skipping preview")
            return
        info_key = min(info_candidates, key=lambda k: k.count("/"))
        prefix = info_key[: -len("meta/info.json")]
        logger.info(f"Preview root: {prefix}")

        info = json_lib.loads(bucket.get_object(info_key).read())
        fps = float(info.get("fps", 30))
        codebase_version = info.get("codebase_version", "")
        is_v3 = codebase_version.startswith("v3")

        preview_prefix = f"previews/{dataset_id}/"
        generated_videos = {}   # cam_name → preview OSS key
        generated_thumbnail = False
        generated_trajectory = False

        # ── helper: 格式化路径模板（如 "videos/chunk-{chunk_index:03d}/..."）──
        def fmt_path(template: str, **kw) -> str:
            def repl(m):
                key = m.group(1)
                width = int(m.group(2)) if m.group(2) else 0
                val = kw.get(key, 0)
                # 有宽度格式（如 :03d）才做整数转换，否则直接字符串替换
                if width:
                    return str(int(val)).zfill(width)
                else:
                    return str(val)
            return re.sub(r"\{(\w+)(?::0?(\d+)d)?\}", repl, template)

        try:
            import pandas as pd
            import pyarrow.parquet as pq
            HAS_PANDAS = True
        except ImportError:
            HAS_PANDAS = False
            logger.warning("pandas/pyarrow 未安装，跳过轨迹/parquet 处理")

        # ── 1. 确定各摄像头 episode_0 的视频文件 key 和时间范围 ────────────────
        # 从 info.json features 中找 dtype=video 的摄像头名
        camera_keys = [
            k for k, v in info.get("features", {}).items()
            if isinstance(v, dict) and v.get("dtype") == "video"
        ]
        if not camera_keys:
            # 兼容：从文件路径猜测
            video_all = [k for k in all_keys if k.startswith(prefix + "videos/") and k.endswith(".mp4")]
            cam_set = set()
            for vk in video_all:
                for part in vk.split("/"):
                    if "observation.images." in part:
                        cam_set.add(part)
            camera_keys = list(cam_set) if cam_set else []

        ep0_start_sec = 0.0
        ep0_end_sec = None   # None = play to end (v2.1 per-episode files)
        ep0_chunk_index = 0
        ep0_file_index = 0
        ep0_row = None       # pd.Series or None

        if is_v3 and HAS_PANDAS:
            # v3.0: 视频是 chunk-level 拼接文件，需读 episodes.parquet 确定 episode_0 时间范围
            ep_parquet_key = next((k for k in all_keys if k.endswith("meta/episodes.parquet")), None)
            if ep_parquet_key:
                try:
                    ep_df = pd.read_parquet(io.BytesIO(bucket.get_object(ep_parquet_key).read()))
                    # 找 episode_index == 0 的行（通常是第一行）
                    if "episode_index" in ep_df.columns:
                        ep0_row = ep_df[ep_df["episode_index"] == 0].iloc[0]
                    else:
                        ep0_row = ep_df.iloc[0]

                    # 尝试各种可能的列名
                    from_idx = int(ep0_row.get("dataset_from_index",
                                   ep0_row.get("from", 0)))
                    to_idx   = int(ep0_row.get("dataset_to_index",
                                   ep0_row.get("to", from_idx)))
                    ep_length = int(ep0_row.get("length", to_idx - from_idx + 1))

                    # 读对应 chunk 的 data parquet，找 episode_0 在文件内的偏移量
                    ep0_chunk_index = int(ep0_row.get("data/chunk_index", 0))
                    ep0_file_index  = int(ep0_row.get("data/file_index", 0))
                    data_path_tmpl = info.get("data_path", "data/chunk-{chunk_index:03d}/file-{file_index:03d}.parquet")
                    data_key = prefix + fmt_path(data_path_tmpl, chunk_index=ep0_chunk_index, file_index=ep0_file_index)
                    # 仅当 data_key 存在时才读
                    data_key_full = next((k for k in all_keys if k == data_key), None)
                    if data_key_full:
                        raw_df = pd.read_parquet(io.BytesIO(bucket.get_object(data_key_full).read()))
                        # 找 episode_0 的第一行在 raw_df 中的位置
                        if "index" in raw_df.columns:
                            file_offsets = raw_df.index[raw_df["index"] == from_idx].tolist()
                        elif "episode_index" in raw_df.columns:
                            file_offsets = raw_df.index[raw_df["episode_index"] == 0].tolist()
                        else:
                            file_offsets = [0]
                        file_offset = file_offsets[0] if file_offsets else 0
                    else:
                        # from_idx 就是文件内偏移（对于 chunk-000/file-000 内第一个 episode）
                        file_offset = from_idx

                    ep0_start_sec = file_offset / fps
                    ep0_end_sec   = (file_offset + ep_length) / fps
                    logger.info(f"Preview v3: episode_0 clip [{ep0_start_sec:.2f}s, {ep0_end_sec:.2f}s]")

                except Exception as e:
                    logger.warning(f"Preview v3: 读取 episodes.parquet 失败，使用全视频: {e}")
                    ep0_start_sec = 0.0
                    ep0_end_sec = None

        # ── 2. 下载视频、裁剪 episode_0、生成缩略图 ─────────────────────────────
        with tempfile.TemporaryDirectory() as tmpdir:
            cam_thumb_paths: list = []   # 每个摄像头的首帧图像路径，用于横向拼接
            for cam_feature in camera_keys:
                cam_name = cam_feature.replace("observation.images.", "")
                oss_video_key = None

                if is_v3:
                    video_path_tmpl = info.get("video_path", "")
                    if video_path_tmpl:
                        rel = fmt_path(video_path_tmpl,
                                       chunk_index=ep0_chunk_index,
                                       file_index=ep0_file_index,
                                       video_key=cam_feature)
                        candidate = prefix + rel
                    else:
                        candidate = None
                    # 先用模板，再在 all_keys 中模糊匹配
                    if candidate and candidate in all_keys:
                        oss_video_key = candidate
                    else:
                        hits = [k for k in all_keys
                                if cam_name in k and k.endswith(".mp4")
                                and k.startswith(prefix + "videos/")]
                        oss_video_key = hits[0] if hits else None
                else:
                    # v2.1: per-episode 文件
                    video_path_tmpl = info.get("video_path", "")
                    if video_path_tmpl:
                        rel = fmt_path(video_path_tmpl,
                                       episode_chunk=0,
                                       episode_index=0,
                                       video_key=cam_feature)
                        candidate = prefix + rel
                    else:
                        candidate = None
                    if candidate and candidate in all_keys:
                        oss_video_key = candidate
                    else:
                        hits = [k for k in all_keys
                                if cam_name in k and "episode_000000" in k and k.endswith(".mp4")]
                        oss_video_key = hits[0] if hits else None

                if not oss_video_key:
                    logger.warning(f"Preview: 找不到摄像头 {cam_name} 的视频文件")
                    continue

                src_path = os.path.join(tmpdir, f"src_{cam_name}.mp4")
                out_path = os.path.join(tmpdir, f"ep0_{cam_name}.mp4")

                logger.info(f"Preview: 下载视频 {oss_video_key} → {src_path}")
                bucket.get_object_to_file(oss_video_key, src_path)

                # 用 ffmpeg 裁剪 episode_0 片段
                ffmpeg_cmd = ["ffmpeg", "-y"]
                if ep0_start_sec and ep0_start_sec > 0:
                    ffmpeg_cmd += ["-ss", str(ep0_start_sec)]
                ffmpeg_cmd += ["-i", src_path]
                if ep0_end_sec is not None:
                    duration = ep0_end_sec - ep0_start_sec
                    ffmpeg_cmd += ["-t", str(duration)]
                ffmpeg_cmd += ["-c:v", "libx264", "-preset", "fast", "-crf", "23",
                               "-an", out_path]

                result = subprocess.run(ffmpeg_cmd, capture_output=True, timeout=300)
                if result.returncode != 0:
                    logger.warning(f"ffmpeg crop failed for {cam_name}: {result.stderr.decode()[:300]}")
                    # fallback: 直接用原文件（v2.1 per-episode 无需裁剪）
                    out_path = src_path

                # 上传裁剪后视频到 previews/
                oss_out_key = preview_prefix + f"{cam_name}.mp4"
                bucket.put_object_from_file(oss_out_key, out_path,
                                             headers={"Content-Type": "video/mp4"})
                generated_videos[cam_name] = oss_out_key
                logger.info(f"Preview: 视频已上传 {oss_out_key}")

                # 用每个摄像头第一帧提取单帧图像，后续统一拼接
                cam_thumb_path = os.path.join(tmpdir, f"thumb_{cam_name}.jpg")
                r2 = subprocess.run(
                    ["ffmpeg", "-y", "-i", out_path,
                     "-vframes", "1", "-q:v", "3", "-vf", "scale=640:-1",
                     cam_thumb_path],
                    capture_output=True, timeout=60,
                )
                if r2.returncode == 0 and os.path.exists(cam_thumb_path):
                    cam_thumb_paths.append(cam_thumb_path)

            # ── 横向拼接所有摄像头首帧 → 生成缩略图 ──────────────────────────
            if cam_thumb_paths:
                thumb_path = os.path.join(tmpdir, "thumbnail.jpg")
                try:
                    from PIL import Image as PILImage
                    frames = [PILImage.open(p) for p in cam_thumb_paths]
                    # 统一高度为最小高度
                    min_h = min(f.height for f in frames)
                    resized = [f.resize((int(f.width * min_h / f.height), min_h), PILImage.LANCZOS)
                               for f in frames]
                    total_w = sum(f.width for f in resized)
                    combined = PILImage.new("RGB", (total_w, min_h))
                    x = 0
                    for f in resized:
                        combined.paste(f, (x, 0))
                        x += f.width
                    combined.save(thumb_path, "JPEG", quality=85)
                except Exception as pil_err:
                    logger.warning(f"PIL 拼接失败，使用单帧: {pil_err}")
                    import shutil
                    shutil.copy(cam_thumb_paths[0], thumb_path)

                if os.path.exists(thumb_path):
                    with open(thumb_path, "rb") as f:
                        thumb_data = f.read()
                    bucket.put_object(preview_prefix + "thumbnail.jpg", thumb_data,
                                      headers={"Content-Type": "image/jpeg"})
                    dataset.thumbnail_path = preview_prefix + "thumbnail.jpg"
                    generated_thumbnail = True
                    logger.info(f"Preview: 缩略图生成成功 ({len(thumb_data)} bytes, {len(cam_thumb_paths)} 摄像头)")

        # ── 3. 提取轨迹数据 ────────────────────────────────────────────────────
        ep0_parquet_key = None
        if is_v3 and HAS_PANDAS:
            # v3.0: 从 data chunk file 读取，过滤出 episode_0 的行
            data_path_tmpl = info.get("data_path", "data/chunk-{chunk_index:03d}/file-{file_index:03d}.parquet")
            ep0_parquet_rel = fmt_path(data_path_tmpl, chunk_index=ep0_chunk_index, file_index=ep0_file_index)
            ep0_parquet_key = next(
                (k for k in all_keys if k == prefix + ep0_parquet_rel), None
            )
        else:
            # v2.1: per-episode parquet
            for obj in oss2.ObjectIterator(bucket, prefix=prefix + "data/"):
                if "episode_000000.parquet" in obj.key or "episode_0.parquet" in obj.key:
                    ep0_parquet_key = obj.key
                    break

        if ep0_parquet_key and HAS_PANDAS:
            try:
                raw_data = bucket.get_object(ep0_parquet_key).read()
                full_df = pd.read_parquet(io.BytesIO(raw_data))

                # v3.0: 只取属于 episode_0 的行
                if is_v3 and "episode_index" in full_df.columns:
                    ep_df_filtered = full_df[full_df["episode_index"] == 0]
                else:
                    ep_df_filtered = full_df

                MAX_FRAMES = 300
                image_cols = [c for c in ep_df_filtered.columns
                              if "image" in c.lower() or "pixel" in c.lower()]
                df_clean = ep_df_filtered.drop(columns=image_cols, errors="ignore").head(MAX_FRAMES)

                trajectory_rows = []
                for _, row in df_clean.iterrows():
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

                bucket.put_object(
                    preview_prefix + "trajectory.json",
                    json_lib.dumps(trajectory_rows).encode(),
                    headers={"Content-Type": "application/json"},
                )
                generated_trajectory = True
                logger.info(f"Preview: 轨迹 {len(trajectory_rows)} 帧已写入")

                # meta_preview.json —— video_keys 指向 previews/ 内的已裁剪视频
                non_image_features = {
                    k: v for k, v in info.get("features", {}).items()
                    if "image" not in k.lower() and k not in image_cols
                }
                meta_preview = {
                    "dataset_id": dataset_id,
                    "episode_index": 0,
                    "fps": fps,
                    "total_frames": len(df_clean),
                    "features": non_image_features,
                    "video_keys": generated_videos,   # cam_name → preview OSS key
                }
                bucket.put_object(
                    preview_prefix + "meta_preview.json",
                    json_lib.dumps(meta_preview).encode(),
                    headers={"Content-Type": "application/json"},
                )

            except Exception as e:
                logger.warning(f"Preview: 轨迹提取失败: {e}")

        elif generated_videos:
            # 无 parquet 但有视频，仍写 meta_preview
            meta_preview = {
                "dataset_id": dataset_id,
                "episode_index": 0,
                "fps": fps,
                "total_frames": 0,
                "features": {},
                "video_keys": generated_videos,
            }
            bucket.put_object(
                preview_prefix + "meta_preview.json",
                json_lib.dumps(meta_preview).encode(),
                headers={"Content-Type": "application/json"},
            )

        # ── 4. 更新数据集状态 ──────────────────────────────────────────────────
        if generated_thumbnail or generated_trajectory or generated_videos:
            dataset.has_preview = True
            dataset.preview_path = preview_prefix
            db.commit()
            logger.info(
                f"Preview done for {dataset_id}: "
                f"videos={list(generated_videos.keys())}, "
                f"thumbnail={generated_thumbnail}, trajectory={generated_trajectory}"
            )
        else:
            logger.warning(f"Preview: 没有生成任何预览内容")

    except Exception as e:
        logger.exception(f"Preview generation failed for dataset {dataset_id}: {e}")
        raise self.retry(exc=e, countdown=120)
    finally:
        db.close()
