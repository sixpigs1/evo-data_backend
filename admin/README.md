# Evo-Data 运维工具

在 ECS 上通过 `docker compose exec api` 运行以下脚本。

---

## 数据库管理 `admin/db.py`

```bash
# 基本用法
docker compose exec api python3 admin/db.py <命令> [参数]
```

| 命令             | 参数                  | 说明                                     |
| ---------------- | --------------------- | ---------------------------------------- |
| `stats`          | —                     | 数据库统计总览（用户/数据集/上传数量等） |
| `users`          | —                     | 列出所有用户                             |
| `user`           | `<phone>`             | 查看单个用户详情                         |
| `datasets`       | —                     | 列出所有数据集                           |
| `dataset`        | `<id>`                | 查看单个数据集详情                       |
| `uploads`        | —                     | 列出最近 30 条上传记录                   |
| `set-admin`      | `<phone>`             | 将用户设为 admin                         |
| `set-level`      | `<phone> <level>`     | 设置用户等级 (normal/contributor/admin)  |
| `set-active`     | `<phone> <0\|1>`      | 启用/禁用用户                            |
| `clear-password` | `<phone>`             | 清空密码（强制短信登录）                 |
| `set-public`     | `<dataset_id> <0\|1>` | 设置数据集公开状态                       |
| `set-tags`       | `<dataset_id> <tags>` | 设置数据集 tags（逗号分隔）              |
| `set-desc`       | `<dataset_id> <desc>` | 设置数据集描述                           |
| `delete-dataset` | `<dataset_id>`        | 删除数据集记录（不删 OSS 文件）          |
| `retry-upload`   | `<upload_id>`         | 重新触发校验任务                         |

### 常用示例

```bash
# 查看总体统计
docker compose exec api python3 admin/db.py stats

# 设置管理员
docker compose exec api python3 admin/db.py set-admin 13700000000

# 将数据集设为公开
docker compose exec api python3 admin/db.py set-public <dataset_id> 1

# 设置数据集 tags
docker compose exec api python3 admin/db.py set-tags <dataset_id> "SO101,家居操作"

# 禁用用户
docker compose exec api python3 admin/db.py set-active 13800000000 0
```

---

## OSS 管理 `admin/oss.py`

```bash
# 基本用法
docker compose exec api python3 admin/oss.py <命令> [参数]
```

| 命令            | 参数                         | 说明                                           |
| --------------- | ---------------------------- | ---------------------------------------------- |
| `overview`      | —                            | 桶内各区域文件数量和大小统计                   |
| `ls`            | `[prefix]`                   | 列出指定前缀下的文件（最多 500 条）            |
| `ls-uploads`    | —                            | 列出临时上传区文件                             |
| `ls-datasets`   | —                            | 列出正式数据集区文件                           |
| `ls-previews`   | —                            | 列出预览文件区文件                             |
| `stat`          | `<prefix>`                   | 统计指定前缀下文件数量、总大小、扩展名分布     |
| `find`          | `<keyword>`                  | 在全桶搜索包含关键词的文件路径                 |
| `get`           | `<oss_key>`                  | 获取并显示文件内容（适合 json/txt 等文本文件） |
| `sign`          | `<oss_key> [秒]`             | 生成签名下载 URL（默认 3600 秒）               |
| `delete`        | `<oss_key>`                  | 删除单个文件（需确认）                         |
| `delete-prefix` | `<prefix>`                   | 删除某前缀下所有文件（需确认，谨慎使用）       |
| `move-dataset`  | `<upload_path> <dataset_id>` | 将上传区文件移动到正式数据集区                 |

### 常用示例

```bash
# 查看桶总览
docker compose exec api python3 admin/oss.py overview

# 查看某数据集的 info.json
docker compose exec api python3 admin/oss.py get datasets/<dataset_id>/meta/info.json

# 查看某上传任务是否有文件
docker compose exec api python3 admin/oss.py stat user_uploads/<user_id>/<upload_id>/

# 生成某文件的临时下载链接（1 小时）
docker compose exec api python3 admin/oss.py sign datasets/<dataset_id>/meta/info.json 3600

# 删除某个上传的临时文件
docker compose exec api python3 admin/oss.py delete-prefix user_uploads/<user_id>/<upload_id>/
```

---

## 快速检查一键脚本

```bash
# 同时查看 DB 统计 + OSS 总览
docker compose exec api sh -c "python3 admin/db.py stats && echo '' && python3 admin/oss.py overview"
```
