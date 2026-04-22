"""
LeRobot 数据集格式校验器
支持 2.1 和 3.0 格式

格式参考:
  v2.1: IPEC-COMMUNITY/libero_10_no_noops_1.0.0_lerobot
  v3.0: sixpigs1/InsertTube

目录结构:
  v2.1:
    meta/
      info.json
      tasks.jsonl
      stats.json (可选)
    data/
      chunk-000/
        episode_000000.parquet
        ...
    videos/ (可选)
      chunk-000/
        observation.images.{cam}/
          episode_000000.mp4

  v3.0:
    meta/
      info.json
      episodes.parquet
      tasks.parquet
      stats.parquet (可选)
    data/
      chunk-000/
        episode_000000.parquet
        ...
    videos/ (可选，或 .mp4 inline)
"""

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

import oss2

from app.config import settings

logger = logging.getLogger(__name__)

# ─── V2.1 info.json 必须字段 ──────────────────────────────────────────────────
V21_INFO_REQUIRED = {
    "codebase_version",
    "fps",
    "total_episodes",
    "total_frames",
    "features",
}

# ─── V3.0 info.json 必须字段 ──────────────────────────────────────────────────
V30_INFO_REQUIRED = {
    "codebase_version",
    "fps",
    "total_episodes",
    "total_frames",
    "features",
    "splits",
    "data_path",
}

# ─── 特征中至少需要存在的键 ───────────────────────────────────────────────────
REQUIRED_FEATURE_KEYS = {"action", "observation.state", "timestamp"}


class FormatVersion(str, Enum):
    V21 = "2.1"
    V30 = "3.0"
    UNKNOWN = "unknown"


@dataclass
class ValidationResult:
    passed: bool
    version: FormatVersion = FormatVersion.UNKNOWN
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    info: Dict[str, Any] = field(default_factory=dict)  # 解析出的 info.json 内容


def _get_oss_bucket() -> oss2.Bucket:
    auth = oss2.Auth(settings.OSS_ACCESS_KEY_ID, settings.OSS_ACCESS_KEY_SECRET)
    return oss2.Bucket(auth, settings.OSS_ENDPOINT, settings.OSS_BUCKET_NAME)


def _list_keys(bucket: oss2.Bucket, prefix: str) -> List[str]:
    """列出 OSS 指定前缀下的所有对象键"""
    keys = []
    for obj in oss2.ObjectIterator(bucket, prefix=prefix):
        keys.append(obj.key)
    return keys


def _key_exists(keys: List[str], suffix: str) -> bool:
    return any(k.endswith(suffix) or suffix in k for k in keys)


def _read_json(bucket: oss2.Bucket, key: str) -> Optional[dict]:
    try:
        result = bucket.get_object(key)
        return json.loads(result.read())
    except Exception as e:
        logger.warning(f"读取 {key} 失败: {e}")
        return None


def validate_dataset(oss_path: str) -> ValidationResult:
    """
    校验 OSS 上 oss_path 目录下的数据集格式。
    oss_path 结尾不含 /
    """
    result = ValidationResult(passed=False)

    try:
        bucket = _get_oss_bucket()
        prefix = oss_path.rstrip("/") + "/"
        all_keys = _list_keys(bucket, prefix)

        if not all_keys:
            result.errors.append(f"目录 {oss_path} 为空或不存在")
            return result

        # 1. 检查 meta/info.json 存在
        info_key = prefix + "meta/info.json"
        if not any(k == info_key for k in all_keys):
            result.errors.append("缺少 meta/info.json")
            return result

        # 2. 读取并解析 info.json
        info = _read_json(bucket, info_key)
        if info is None:
            result.errors.append("meta/info.json 无法读取或不是合法 JSON")
            return result
        result.info = info

        # 3. 判断版本
        codebase_version = info.get("codebase_version", "")
        if codebase_version.startswith("v2"):
            version = FormatVersion.V21
        elif codebase_version.startswith("v3"):
            version = FormatVersion.V30
        else:
            # 尝试从结构判断
            has_episodes_parquet = any("meta/episodes.parquet" in k for k in all_keys)
            version = FormatVersion.V30 if has_episodes_parquet else FormatVersion.V21

        result.version = version

        # 4. 校验必需字段
        required = V30_INFO_REQUIRED if version == FormatVersion.V30 else V21_INFO_REQUIRED
        missing = required - set(info.keys())
        if missing:
            result.errors.append(f"meta/info.json 缺少必要字段: {missing}")

        # 5. 校验 features
        features = info.get("features", {})
        if not isinstance(features, dict):
            result.errors.append("meta/info.json 中 features 格式不正确")
        else:
            missing_features = REQUIRED_FEATURE_KEYS - set(features.keys())
            if missing_features:
                result.warnings.append(f"features 中缺少推荐字段: {missing_features}")

        # 6. 校验 meta 元文件
        if version == FormatVersion.V21:
            if not any("meta/tasks.jsonl" in k for k in all_keys):
                result.warnings.append("缺少 meta/tasks.jsonl（v2.1 推荐）")
        else:
            if not any("meta/episodes.parquet" in k for k in all_keys):
                result.errors.append("v3.0 格式缺少 meta/episodes.parquet")
            if not any("meta/tasks.parquet" in k for k in all_keys):
                result.warnings.append("缺少 meta/tasks.parquet（v3.0 推荐）")

        # 7. 校验 data 目录存在
        has_data = any("/data/" in k or k.startswith(prefix + "data/") for k in all_keys)
        if not has_data:
            result.errors.append("缺少 data/ 目录")

        # 8. 校验至少有一个 episode parquet
        has_episode = any("episode_" in k and k.endswith(".parquet") for k in all_keys)
        if not has_episode:
            result.errors.append("未找到 episode 数据文件（data/chunk-*/episode_*.parquet）")

        # 9. 校验 total_episodes > 0
        total_episodes = info.get("total_episodes", 0)
        if not isinstance(total_episodes, int) or total_episodes <= 0:
            result.errors.append("total_episodes 必须为正整数")

        # 10. 校验 fps
        fps = info.get("fps", 0)
        if not isinstance(fps, (int, float)) or fps <= 0:
            result.errors.append("fps 必须为正数")

        result.passed = len(result.errors) == 0

    except Exception as e:
        logger.exception(f"校验过程出现异常: {e}")
        result.errors.append(f"校验异常: {str(e)}")

    return result
