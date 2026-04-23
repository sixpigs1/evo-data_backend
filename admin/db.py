"""
RDS MySQL 运维工具
用法（在 ECS 上）：
    docker compose exec api python3 admin/db.py <命令> [参数]

命令列表：
    users                     列出所有用户
    user <phone>              查看单个用户详情
    datasets                  列出所有数据集
    dataset <id>              查看单个数据集详情
    uploads                   列出最近上传记录
    stats                     数据库统计总览

    set-admin <phone>         将用户设为 admin
    set-level <phone> <level> 设置用户等级 (normal/contributor/admin)
    set-active <phone> <0|1>  启用/禁用用户
    clear-password <phone>    清空用户密码（强制短信登录）

    set-public <dataset_id> <0|1>   设置数据集公开状态
    set-tags <dataset_id> <tags>    设置数据集 tags（逗号分隔）
    set-desc <dataset_id> <desc>    设置数据集描述
    delete-dataset <dataset_id>     删除数据集记录（不删 OSS 文件）

    retry-upload <upload_id>        重新触发校验任务
"""

import sys
import os

# 将项目根目录加入 path，使 app.* 可以直接 import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "mysql+pymysql://evodata:cqmygYSDSS123@rm-bp1y7lfvg5u0hxh8a.mysql.rds.aliyuncs.com:3306/evo_data?charset=utf8mb4"
)

engine = create_engine(DATABASE_URL, echo=False)


# ─── 辅助函数 ──────────────────────────────────────────────────────────────────

def hr(char="─", width=80):
    print(char * width)

def section(title):
    print()
    hr()
    print(f"  {title}")
    hr()


# ─── 查询命令 ──────────────────────────────────────────────────────────────────

def cmd_users():
    section("所有用户")
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, phone, level, rank, is_active, created_at
            FROM users ORDER BY created_at DESC
        """)).fetchall()
    print(f"{'手机号':15}  {'等级':12}  {'积分':6}  {'激活':4}  {'创建时间':20}  ID")
    hr("-")
    for r in rows:
        print(f"{r.phone:15}  {r.level:12}  {r.rank:<6}  {'✓' if r.is_active else '✗':4}  {str(r.created_at)[:19]:20}  {r.id}")
    print(f"\n共 {len(rows)} 个用户")


def cmd_user(phone):
    section(f"用户详情：{phone}")
    with engine.connect() as conn:
        user = conn.execute(text(
            "SELECT * FROM users WHERE phone=:p"
        ), {"p": phone}).fetchone()
        if not user:
            print("❌ 用户不存在")
            return
        for k, v in zip(user._fields, user):
            if k == "hashed_password":
                v = "***" if v else "(未设置)"
            print(f"  {k:20} : {v}")

        # 数据集数量
        ds_count = conn.execute(text(
            "SELECT COUNT(*) FROM datasets WHERE owner_id=:uid"
        ), {"uid": user.id}).scalar()
        contrib = conn.execute(text(
            "SELECT COUNT(*) FROM contributions WHERE user_id=:uid AND status='passed'"
        ), {"uid": user.id}).scalar()
        print(f"  {'拥有数据集':20} : {ds_count}")
        print(f"  {'有效贡献数':20} : {contrib}")


def cmd_datasets():
    section("所有数据集")
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT d.id, d.name, d.is_public, d.has_preview, d.version,
                   d.total_episodes, d.total_frames, d.tags, u.phone
            FROM datasets d JOIN users u ON d.owner_id = u.id
            ORDER BY d.created_at DESC
        """)).fetchall()
    print(f"{'名称':40}  {'公开':4}  {'预览':4}  {'版本':6}  {'集数':6}  {'上传者':15}")
    hr("-")
    for r in rows:
        name = r.name[:38] if len(r.name) > 38 else r.name
        print(f"{name:40}  {'✓' if r.is_public else '✗':4}  {'✓' if r.has_preview else '✗':4}  "
              f"{str(r.version or '?'):6}  {str(r.total_episodes or '?'):6}  {r.phone:15}")
        if r.tags:
            print(f"  {'':40}  tags: {r.tags}")
    print(f"\n共 {len(rows)} 个数据集")


def cmd_dataset(dataset_id):
    section(f"数据集详情：{dataset_id}")
    with engine.connect() as conn:
        d = conn.execute(text(
            "SELECT d.*, u.phone FROM datasets d JOIN users u ON d.owner_id=u.id WHERE d.id=:id"
        ), {"id": dataset_id}).fetchone()
        if not d:
            print("❌ 数据集不存在")
            return
        for k, v in zip(d._fields, d):
            print(f"  {k:20} : {v}")


def cmd_uploads():
    section("最近 30 条上传记录")
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT u.id, u.dataset_name, u.status, u.detected_version,
                   u.created_at, usr.phone, u.error_message
            FROM uploads u JOIN users usr ON u.user_id = usr.id
            ORDER BY u.created_at DESC LIMIT 30
        """)).fetchall()
    print(f"{'数据集名称':35}  {'状态':12}  {'上传者':15}  {'时间':20}")
    hr("-")
    for r in rows:
        name = (r.dataset_name or "?")[:33]
        print(f"{name:35}  {r.status:12}  {r.phone:15}  {str(r.created_at)[:19]}")
        if r.error_message:
            print(f"  {'':35}  ⚠ {r.error_message[:60]}")
    print(f"\n共 {len(rows)} 条记录（显示最近 30 条）")


def cmd_stats():
    section("数据库统计总览")
    with engine.connect() as conn:
        def scalar(sql):
            return conn.execute(text(sql)).scalar() or 0

        n_users      = scalar("SELECT COUNT(*) FROM users")
        n_admin      = scalar("SELECT COUNT(*) FROM users WHERE level='admin'")
        n_contrib    = scalar("SELECT COUNT(*) FROM users WHERE level='contributor'")
        n_normal     = scalar("SELECT COUNT(*) FROM users WHERE level='normal'")
        n_datasets   = scalar("SELECT COUNT(*) FROM datasets")
        n_public     = scalar("SELECT COUNT(*) FROM datasets WHERE is_public=1")
        n_preview    = scalar("SELECT COUNT(*) FROM datasets WHERE has_preview=1")
        n_uploads    = scalar("SELECT COUNT(*) FROM uploads")
        n_passed     = scalar("SELECT COUNT(*) FROM uploads WHERE status='passed'")
        n_failed     = scalar("SELECT COUNT(*) FROM uploads WHERE status='failed'")
        n_pending    = scalar("SELECT COUNT(*) FROM uploads WHERE status='pending' OR status='validating'")
        total_frames = scalar("SELECT SUM(total_frames) FROM datasets")
        total_eps    = scalar("SELECT SUM(total_episodes) FROM datasets")

    print(f"  用户总数        : {n_users}")
    print(f"  管理员数        : {n_admin}")
    print(f"  贡献者数        : {n_contrib}")
    print(f"  普通用户数      : {n_normal}")
    print()
    print(f"  数据集总数      : {n_datasets}")
    print(f"  公开数据集      : {n_public}")
    print(f"  有预览的数据集  : {n_preview}")
    print()
    print(f"  上传记录总数    : {n_uploads}")
    print(f"  通过校验        : {n_passed}")
    print(f"  校验失败        : {n_failed}")
    print(f"  待处理          : {n_pending}")
    print()
    print(f"  总 episodes     : {int(total_eps):,}")
    print(f"  总 frames       : {int(total_frames):,}")


# ─── 修改命令 ──────────────────────────────────────────────────────────────────

def cmd_set_admin(phone):
    with engine.begin() as conn:
        r = conn.execute(text(
            "UPDATE users SET level='admin', rank=100 WHERE phone=:p"
        ), {"p": phone})
    if r.rowcount:
        print(f"✅ {phone} 已设为 admin")
    else:
        print(f"❌ 用户 {phone} 不存在")


def cmd_set_level(phone, level):
    if level not in ("normal", "contributor", "admin"):
        print("❌ level 必须是 normal / contributor / admin")
        return
    with engine.begin() as conn:
        r = conn.execute(text(
            "UPDATE users SET level=:level WHERE phone=:p"
        ), {"level": level, "p": phone})
    print(f"✅ {phone} 等级已设为 {level}" if r.rowcount else f"❌ 用户 {phone} 不存在")


def cmd_set_active(phone, active):
    val = 1 if str(active) in ("1", "true", "True") else 0
    with engine.begin() as conn:
        r = conn.execute(text(
            "UPDATE users SET is_active=:v WHERE phone=:p"
        ), {"v": val, "p": phone})
    status = "启用" if val else "禁用"
    print(f"✅ 用户 {phone} 已{status}" if r.rowcount else f"❌ 用户 {phone} 不存在")


def cmd_clear_password(phone):
    with engine.begin() as conn:
        r = conn.execute(text(
            "UPDATE users SET hashed_password=NULL WHERE phone=:p"
        ), {"p": phone})
    print(f"✅ {phone} 密码已清空" if r.rowcount else f"❌ 用户 {phone} 不存在")


def cmd_set_public(dataset_id, public):
    val = 1 if str(public) in ("1", "true", "True") else 0
    with engine.begin() as conn:
        r = conn.execute(text(
            "UPDATE datasets SET is_public=:v WHERE id=:id"
        ), {"v": val, "id": dataset_id})
    status = "公开" if val else "私有"
    print(f"✅ 数据集已设为{status}" if r.rowcount else f"❌ 数据集 {dataset_id} 不存在")


def cmd_set_tags(dataset_id, tags):
    with engine.begin() as conn:
        r = conn.execute(text(
            "UPDATE datasets SET tags=:t WHERE id=:id"
        ), {"t": tags, "id": dataset_id})
    print(f"✅ tags 已更新为: {tags}" if r.rowcount else f"❌ 数据集 {dataset_id} 不存在")


def cmd_set_desc(dataset_id, desc):
    with engine.begin() as conn:
        r = conn.execute(text(
            "UPDATE datasets SET description=:d WHERE id=:id"
        ), {"d": desc, "id": dataset_id})
    print(f"✅ 描述已更新" if r.rowcount else f"❌ 数据集 {dataset_id} 不存在")


def cmd_delete_dataset(dataset_id):
    confirm = input(f"⚠️  确认删除数据集 {dataset_id} 的数据库记录？(yes/no): ")
    if confirm.lower() != "yes":
        print("已取消")
        return
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM contributions WHERE dataset_id=:id"), {"id": dataset_id})
        r = conn.execute(text("DELETE FROM datasets WHERE id=:id"), {"id": dataset_id})
    print(f"✅ 已删除" if r.rowcount else f"❌ 数据集 {dataset_id} 不存在")


def cmd_retry_upload(upload_id):
    with engine.begin() as conn:
        r = conn.execute(text(
            "UPDATE uploads SET status='pending', error_message=NULL WHERE id=:id"
        ), {"id": upload_id})
    if not r.rowcount:
        print(f"❌ upload {upload_id} 不存在")
        return
    # 触发 Celery 任务
    try:
        from app.worker.tasks import validate_dataset_task
        validate_dataset_task.delay(upload_id)
        print(f"✅ 已重新触发校验任务: {upload_id}")
    except Exception as e:
        print(f"⚠️  记录已重置，但触发 Celery 任务失败: {e}")
        print("   请手动执行: docker compose restart worker")


# ─── 入口 ──────────────────────────────────────────────────────────────────────

COMMANDS = {
    "users":          (cmd_users,          0),
    "user":           (cmd_user,           1),
    "datasets":       (cmd_datasets,       0),
    "dataset":        (cmd_dataset,        1),
    "uploads":        (cmd_uploads,        0),
    "stats":          (cmd_stats,          0),
    "set-admin":      (cmd_set_admin,      1),
    "set-level":      (cmd_set_level,      2),
    "set-active":     (cmd_set_active,     2),
    "clear-password": (cmd_clear_password, 1),
    "set-public":     (cmd_set_public,     2),
    "set-tags":       (cmd_set_tags,       2),
    "set-desc":       (cmd_set_desc,       2),
    "delete-dataset": (cmd_delete_dataset, 1),
    "retry-upload":   (cmd_retry_upload,   1),
}

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help", "help"):
        print(__doc__)
        sys.exit(0)

    cmd = args[0]
    if cmd not in COMMANDS:
        print(f"❌ 未知命令: {cmd}")
        print("运行 python3 admin/db.py help 查看帮助")
        sys.exit(1)

    func, nargs = COMMANDS[cmd]
    provided = len(args) - 1
    if provided < nargs:
        print(f"❌ 命令 '{cmd}' 需要 {nargs} 个参数，提供了 {provided} 个")
        sys.exit(1)

    func(*args[1:nargs+1])
