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
        print(f"当前状态  : {upload.status.value}")
        print(f"dataset_name: {upload.dataset_name}")

        # 重置状态为 pending，避免任务被忽略
        upload.status = UploadStatus.pending
        upload.error_message = None
        db.commit()

        # 异步触发
        validate_dataset_task.delay(
            str(upload.id),
            upload.dataset_name,
            None,   # tags 从 upload 记录里没存，需要从 dataset 或手动传入
            False,  # is_public
        )
        print(f"\n✅ 已触发校验任务，请用 docker compose logs -f worker 查看进度。")
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
    else:
        cmd_revalidate(args[0])
