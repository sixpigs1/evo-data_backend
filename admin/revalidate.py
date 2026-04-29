#!/usr/bin/env python3
"""
手动触发数据集校验脚本
用法：
  # 对指定 upload_id 重新触发校验
  docker compose exec api python3 admin/revalidate.py <upload_id>

  # 对指定 OSS 路径直接运行校验（不写数据库，仅打印结果）
  docker compose exec api python3 admin/revalidate.py --dry-run <oss_path>

  # 列出最近 N 条失败的 upload
  docker compose exec api python3 admin/revalidate.py --list-failed [N]

  # 对指定 dataset_id 重新触发预览生成
  docker compose exec api python3 admin/revalidate.py --preview <dataset_id>
"""
import sys
import os

# 确保项目根在 PATH 中
sys.path.insert(0, "/app")


def cmd_dry_run(oss_path: str):
    """直接校验 OSS 路径，不写数据库"""
    from app.datasets.validator import validate_dataset
    print(f"\n▶  校验路径: {oss_path}\n")
    result = validate_dataset(oss_path)
    print(f"{'✅ PASSED' if result.passed else '❌ FAILED'}  版本={result.version.value}")
    if result.errors:
        print("\n错误:")
        for e in result.errors:
            print(f"  ✗ {e}")
    if result.warnings:
        print("\n警告:")
        for w in result.warnings:
            print(f"  ⚠  {w}")
    if result.info:
        print(f"\ninfo.json 摘要:")
        for k in ("codebase_version", "fps", "total_episodes", "total_frames"):
            if k in result.info:
                print(f"  {k}: {result.info[k]}")


def cmd_list_failed(n: int = 10):
    """列出最近 N 条失败的 upload"""
    from app.database import SessionLocal
    from app.models import Upload, UploadStatus
    db = SessionLocal()
    try:
        rows = (
            db.query(Upload)
            .filter(Upload.status == UploadStatus.failed)
            .order_by(Upload.created_at.desc())
            .limit(n)
            .all()
        )
        if not rows:
            print("没有失败的上传记录。")
            return
        print(f"\n{'ID':<38}  {'创建时间':<20}  {'错误信息'}")
        print("-" * 100)
        for r in rows:
            print(f"{str(r.id):<38}  {str(r.created_at):<20}  {r.error_message or '-'}")
    finally:
        db.close()


def cmd_revalidate(upload_id: str):
    """对已有 upload 重新触发 Celery 校验任务"""
    from app.database import SessionLocal
    from app.models import Upload, UploadStatus
    from app.worker.tasks import validate_dataset_task

    db = SessionLocal()
    try:
        upload = db.query(Upload).filter(Upload.id == upload_id).first()
        if not upload:
            print(f"❌ 找不到 upload_id={upload_id}")
            sys.exit(1)

        print(f"upload_id : {upload.id}")
        print(f"oss_path  : {upload.oss_path}")
        print(f"当前状态  : {upload.status.value if hasattr(upload.status, 'value') else upload.status}")
        print(f"dataset_name: {upload.dataset_name}")

        # 无论当前状态如何，强制重置为 pending 再触发
        upload.status = UploadStatus.pending
        upload.error_message = None
        db.commit()

        # 异步触发（用关键字参数，兼容 tasks.py 新旧签名）
        validate_dataset_task.delay(
            str(upload.id),
            description=upload.dataset_name,
        )
        print(f"\n✅ 已触发校验任务，请用 docker compose logs -f worker 查看进度。")
    finally:
        db.close()


def cmd_preview(dataset_id: str):
    """对已有 dataset_id 重新触发预览生成任务"""
    from app.database import SessionLocal
    from app.models import Dataset
    from app.worker.tasks import generate_preview_task

    db = SessionLocal()
    try:
        d = db.query(Dataset).filter(Dataset.id == dataset_id).first()
        if not d:
            print(f"❌ 找不到 dataset_id={dataset_id}")
            sys.exit(1)
        print(f"dataset_id  : {d.id}")
        print(f"name        : {d.name}")
        print(f"oss_path    : {d.oss_path}")
        print(f"has_preview : {d.has_preview}")
        generate_preview_task.delay(str(d.id))
        print("\n✅ 已触发预览生成任务，请用 docker compose logs -f worker 查看进度。")
    finally:
        db.close()


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)

    if args[0] == "--dry-run" and len(args) >= 2:
        cmd_dry_run(args[1])
    elif args[0] == "--list-failed":
        n = int(args[1]) if len(args) >= 2 else 10
        cmd_list_failed(n)
    elif args[0] == "--preview" and len(args) >= 2:
        cmd_preview(args[1])
    else:
        cmd_revalidate(args[0])
