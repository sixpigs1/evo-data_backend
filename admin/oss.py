"""
OSS 桶运维工具
用法（在 ECS 上）：
    docker compose exec api python3 admin/oss.py <命令> [参数]

命令列表：
    overview                        桶内文件总览（目录级别统计）
    ls [prefix]                     列出指定前缀下的文件
    ls-uploads                      列出临时上传区所有文件
    ls-datasets                     列出正式数据集区所有文件
    ls-previews                     列出预览文件区所有文件
    stat <prefix>                   统计指定前缀下的文件数量和总大小
    find <keyword>                  在全桶搜索包含关键词的文件路径

    get <oss_key>                   获取文件内容（文本文件，如 info.json）
    sign <oss_key> [expires_sec]    生成签名下载 URL（默认 3600 秒）

    delete <oss_key>                删除单个文件（需确认）
    delete-prefix <prefix>          删除某前缀下所有文件（需确认，谨慎使用）
    move-dataset <upload_path> <dataset_id>   将上传区文件移动到正式数据集区
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OSS_ACCESS_KEY_ID     = os.environ.get("OSS_ACCESS_KEY_ID", "")
OSS_ACCESS_KEY_SECRET = os.environ.get("OSS_ACCESS_KEY_SECRET", "")
OSS_ENDPOINT          = os.environ.get("OSS_ENDPOINT", "https://oss-cn-hangzhou.aliyuncs.com")
OSS_BUCKET_NAME       = os.environ.get("OSS_BUCKET_NAME", "evo-data")

# 如果环境变量没有，尝试从 app.config 读取
if not OSS_ACCESS_KEY_ID:
    try:
        from app.config import settings
        OSS_ACCESS_KEY_ID     = settings.OSS_ACCESS_KEY_ID
        OSS_ACCESS_KEY_SECRET = settings.OSS_ACCESS_KEY_SECRET
        OSS_ENDPOINT          = settings.OSS_ENDPOINT
        OSS_BUCKET_NAME       = settings.OSS_BUCKET_NAME
    except Exception:
        pass

import oss2


def get_bucket():
    auth = oss2.Auth(OSS_ACCESS_KEY_ID, OSS_ACCESS_KEY_SECRET)
    return oss2.Bucket(auth, OSS_ENDPOINT, OSS_BUCKET_NAME)


def fmt_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 ** 2:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 ** 3:
        return f"{size_bytes / 1024**2:.1f} MB"
    return f"{size_bytes / 1024**3:.2f} GB"


def hr(char="─", width=80):
    print(char * width)

def section(title):
    print()
    hr()
    print(f"  {title}")
    hr()


# ─── 查询命令 ──────────────────────────────────────────────────────────────────

def cmd_overview():
    section(f"OSS 桶总览：{OSS_BUCKET_NAME}")
    bucket = get_bucket()
    top_prefixes = ["user_uploads/", "datasets/", "previews/"]
    total_files = 0
    total_size = 0
    for prefix in top_prefixes:
        count = 0
        size = 0
        for obj in oss2.ObjectIterator(bucket, prefix=prefix):
            count += 1
            size += obj.size
        total_files += count
        total_size += size
        print(f"  {prefix:20}  {count:6} 个文件   {fmt_size(size):>12}")

    # 其他顶层文件
    other_count = 0
    other_size = 0
    result = bucket.list_objects(delimiter="/", max_keys=1000)
    for obj in result.object_list:
        other_count += 1
        other_size += obj.size
    if other_count:
        print(f"  {'(根目录文件)':20}  {other_count:6} 个文件   {fmt_size(other_size):>12}")
        total_files += other_count
        total_size += other_size

    hr("-")
    print(f"  {'合计':20}  {total_files:6} 个文件   {fmt_size(total_size):>12}")


def cmd_ls(prefix=""):
    section(f"文件列表：{prefix or '(根目录)'}")
    bucket = get_bucket()
    count = 0
    for obj in oss2.ObjectIterator(bucket, prefix=prefix, max_keys=500):
        print(f"  {fmt_size(obj.size):>10}   {obj.last_modified}   {obj.key}")
        count += 1
        if count >= 500:
            print("  ... (显示前 500 条，使用 stat 命令查看完整统计)")
            break
    print(f"\n共显示 {count} 个文件")


def cmd_ls_uploads():
    cmd_ls("user_uploads/")


def cmd_ls_datasets():
    cmd_ls("datasets/")


def cmd_ls_previews():
    cmd_ls("previews/")


def cmd_stat(prefix):
    section(f"统计：{prefix}")
    bucket = get_bucket()
    count = 0
    total = 0
    ext_map = {}
    for obj in oss2.ObjectIterator(bucket, prefix=prefix):
        count += 1
        total += obj.size
        ext = os.path.splitext(obj.key)[1].lower() or "(无扩展名)"
        ext_map[ext] = ext_map.get(ext, 0) + obj.size

    print(f"  文件总数  : {count:,}")
    print(f"  总大小    : {fmt_size(total)} ({total:,} 字节)")
    print()
    print("  按扩展名分布：")
    for ext, sz in sorted(ext_map.items(), key=lambda x: -x[1]):
        print(f"    {ext:15}  {fmt_size(sz):>10}")


def cmd_find(keyword):
    section(f"搜索关键词：{keyword}")
    bucket = get_bucket()
    count = 0
    for obj in oss2.ObjectIterator(bucket):
        if keyword.lower() in obj.key.lower():
            print(f"  {fmt_size(obj.size):>10}   {obj.key}")
            count += 1
    print(f"\n找到 {count} 个匹配文件")


def cmd_get(oss_key):
    section(f"文件内容：{oss_key}")
    bucket = get_bucket()
    try:
        obj = bucket.get_object(oss_key)
        content = obj.read().decode("utf-8", errors="replace")
        # 超过 4KB 只显示前后
        if len(content) > 4096:
            print(content[:2000])
            print(f"\n... (文件共 {len(content)} 字节，中间省略) ...\n")
            print(content[-500:])
        else:
            print(content)
    except oss2.exceptions.NoSuchKey:
        print(f"❌ 文件不存在: {oss_key}")


def cmd_sign(oss_key, expires_sec=3600):
    section(f"签名 URL：{oss_key}")
    bucket = get_bucket()
    try:
        expires = int(expires_sec)
        url = bucket.sign_url("GET", oss_key, expires)
        print(f"  有效期  : {expires} 秒")
        print(f"  URL     : {url}")
    except oss2.exceptions.NoSuchKey:
        print(f"❌ 文件不存在: {oss_key}")


# ─── 写入/删除命令 ─────────────────────────────────────────────────────────────

def cmd_delete(oss_key):
    confirm = input(f"⚠️  确认删除文件 {oss_key}？(yes/no): ")
    if confirm.lower() != "yes":
        print("已取消")
        return
    bucket = get_bucket()
    bucket.delete_object(oss_key)
    print(f"✅ 已删除: {oss_key}")


def cmd_delete_prefix(prefix):
    bucket = get_bucket()
    # 先统计
    keys = [obj.key for obj in oss2.ObjectIterator(bucket, prefix=prefix)]
    if not keys:
        print(f"❌ 前缀 {prefix} 下没有文件")
        return
    print(f"⚠️  将删除 {len(keys)} 个文件，前缀: {prefix}")
    print("  示例：", keys[:3])
    confirm = input("确认删除？(yes/no): ")
    if confirm.lower() != "yes":
        print("已取消")
        return

    deleted = 0
    # 批量删除（每次最多 1000 个）
    batch = []
    for key in keys:
        batch.append(key)
        if len(batch) >= 1000:
            bucket.batch_delete_objects(batch)
            deleted += len(batch)
            batch = []
    if batch:
        bucket.batch_delete_objects(batch)
        deleted += len(batch)

    print(f"✅ 已删除 {deleted} 个文件")


def cmd_move_dataset(upload_path, dataset_id):
    """将上传区的文件复制到正式数据集区，完成后删除原文件"""
    bucket = get_bucket()
    upload_path = upload_path.rstrip("/") + "/"
    dest_prefix = f"datasets/{dataset_id}/"

    # 列出所有源文件
    keys = [obj.key for obj in oss2.ObjectIterator(bucket, prefix=upload_path)]
    if not keys:
        print(f"❌ 源路径 {upload_path} 下没有文件")
        return

    print(f"  源路径   : {upload_path}  ({len(keys)} 个文件)")
    print(f"  目标路径 : {dest_prefix}")
    confirm = input("确认移动？(yes/no): ")
    if confirm.lower() != "yes":
        print("已取消")
        return

    moved = 0
    for src_key in keys:
        relative = src_key[len(upload_path):]
        dst_key = dest_prefix + relative
        # OSS copy_object
        bucket.copy_object(OSS_BUCKET_NAME, src_key, dst_key)
        bucket.delete_object(src_key)
        moved += 1
        if moved % 20 == 0:
            print(f"  进度: {moved}/{len(keys)}")

    print(f"✅ 已移动 {moved} 个文件到 {dest_prefix}")
    print("  请手动更新数据库中对应 Dataset 的 oss_path 字段：")
    print(f"  python3 admin/db.py set-desc <dataset_id> ...  (或直接 SQL)")


# ─── 入口 ──────────────────────────────────────────────────────────────────────

COMMANDS = {
    "overview":       (cmd_overview,       0),
    "ls":             (cmd_ls,             0),   # 参数可选
    "ls-uploads":     (cmd_ls_uploads,     0),
    "ls-datasets":    (cmd_ls_datasets,    0),
    "ls-previews":    (cmd_ls_previews,    0),
    "stat":           (cmd_stat,           1),
    "find":           (cmd_find,           1),
    "get":            (cmd_get,            1),
    "sign":           (cmd_sign,           1),   # 第2个参数可选
    "delete":         (cmd_delete,         1),
    "delete-prefix":  (cmd_delete_prefix,  1),
    "move-dataset":   (cmd_move_dataset,   2),
}

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help", "help"):
        print(__doc__)
        sys.exit(0)

    cmd = args[0]
    if cmd not in COMMANDS:
        print(f"❌ 未知命令: {cmd}")
        print("运行 python3 admin/oss.py help 查看帮助")
        sys.exit(1)

    func, nargs = COMMANDS[cmd]
    provided = len(args) - 1
    if provided < nargs:
        print(f"❌ 命令 '{cmd}' 需要至少 {nargs} 个参数，提供了 {provided} 个")
        sys.exit(1)

    func(*args[1:])
