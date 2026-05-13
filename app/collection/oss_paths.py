"""OSS path builders for collection data."""

from __future__ import annotations

import re
from typing import Any


def collection_run_raw_oss_path(run: Any, env_prefix: str) -> str:
    dataset_slug = oss_path_segment(str(run.dataset_name))
    env = oss_path_segment(env_prefix)
    return (
        f"{env}/orgs/{run.org_id}/users/{run.user_id}/"
        f"raw/collection-runs/{run.id}/{dataset_slug}/"
    )


def collection_run_id_from_raw_oss_path(upload_dir: str, env_prefix: str, user_id: str) -> str | None:
    parts = upload_dir.strip("/").split("/")
    env = oss_path_segment(env_prefix)
    if len(parts) != 9:
        return None
    if parts[0] != env or parts[1] != "orgs" or parts[3] != "users":
        return None
    if parts[4] != str(user_id) or parts[5] != "raw" or parts[6] != "collection-runs":
        return None
    return parts[7]


def oss_path_segment(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    normalized = normalized.strip("._-")
    return normalized or "dataset"
