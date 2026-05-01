"""Data collection task API."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from typing import Any, Literal, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import (
    CollectionAssignment,
    CollectionRun,
    CollectionRunStatus,
    CollectionTask,
    User,
)

router = APIRouter(prefix="/collection", tags=["collection"])

TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _today() -> date:
    return datetime.now(TZ_SHANGHAI).date()


def _json_dumps(value: dict[str, Any] | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_loads(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    return json.loads(value)


def _validate_phone(value: str) -> str:
    value = value.strip()
    if not value.isdigit() or len(value) != 11 or not value.startswith("1"):
        raise ValueError("手机号格式不正确")
    return value


def _user_level(user: User) -> str:
    return user.level.value if hasattr(user.level, "value") else str(user.level)


def _run_status(run: CollectionRun) -> str:
    return run.status.value if hasattr(run.status, "value") else str(run.status)


def _require_admin(user: User) -> None:
    if _user_level(user) != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可访问")


def _task_payload(task: CollectionTask) -> dict[str, Any]:
    return {
        "task": task.task_prompt,
        "num_episodes": task.num_episodes,
        "fps": task.fps,
        "episode_time_s": task.episode_time_s,
        "reset_time_s": task.reset_time_s,
        "use_cameras": task.use_cameras,
        "arms": task.arms,
    }


def _run_duration(
    *,
    total_frames: int | None,
    fps: int | None,
    duration_seconds: int | None,
    saved_episodes: int | None,
    episode_time_s: int | None,
) -> int:
    if total_frames is not None and fps and fps > 0:
        return round(total_frames / fps)
    if duration_seconds is not None:
        return max(duration_seconds, 0)
    if saved_episodes is not None and episode_time_s is not None:
        return max(saved_episodes, 0) * max(episode_time_s, 0)
    return 0


class CollectionTaskBase(BaseModel):
    name: str
    description: Optional[str] = None
    task_prompt: str
    num_episodes: int = 10
    fps: int = 30
    episode_time_s: int = 300
    reset_time_s: int = 10
    use_cameras: bool = True
    arms: str = ""
    dataset_prefix: str = "rec"
    is_active: bool = True

    @field_validator("name", "task_prompt", "dataset_prefix")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("不能为空")
        return value

    @field_validator("num_episodes", "fps", "episode_time_s")
    @classmethod
    def validate_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("必须大于 0")
        return value

    @field_validator("reset_time_s")
    @classmethod
    def validate_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("不得小于 0")
        return value


class CollectionTaskCreate(CollectionTaskBase):
    pass


class CollectionTaskUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    task_prompt: Optional[str] = None
    num_episodes: Optional[int] = None
    fps: Optional[int] = None
    episode_time_s: Optional[int] = None
    reset_time_s: Optional[int] = None
    use_cameras: Optional[bool] = None
    arms: Optional[str] = None
    dataset_prefix: Optional[str] = None
    is_active: Optional[bool] = None

    @field_validator("name", "task_prompt", "dataset_prefix")
    @classmethod
    def validate_optional_required_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return CollectionTaskBase.validate_required_text(value)

    @field_validator("num_episodes", "fps", "episode_time_s")
    @classmethod
    def validate_optional_positive(cls, value: int | None) -> int | None:
        if value is None:
            return None
        return CollectionTaskBase.validate_positive(value)

    @field_validator("reset_time_s")
    @classmethod
    def validate_optional_non_negative(cls, value: int | None) -> int | None:
        if value is None:
            return None
        return CollectionTaskBase.validate_non_negative(value)


class CollectionTaskResponse(CollectionTaskBase):
    id: str
    created_by_id: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class AssignmentCreate(BaseModel):
    phone: str
    task_id: str
    target_date: date
    target_seconds: int
    is_active: bool = True

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        return _validate_phone(value)

    @field_validator("target_seconds")
    @classmethod
    def validate_target_seconds(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("目标时长必须大于 0")
        return value


class AssignmentResponse(BaseModel):
    id: str
    user_id: Optional[str] = None
    phone: str
    task_id: str
    task_name: str
    target_date: date
    target_seconds: int
    completed_seconds: int
    active_run_id: Optional[str] = None
    is_active: bool
    task_params: dict[str, Any]


class RunStartRequest(BaseModel):
    assignment_id: str
    dataset_name: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None
    client_info: Optional[dict[str, Any]] = None


class RunHeartbeatRequest(BaseModel):
    saved_episodes: Optional[int] = None
    total_frames: Optional[int] = None
    fps: Optional[int] = None
    duration_seconds: Optional[int] = None
    metadata: Optional[dict[str, Any]] = None
    client_info: Optional[dict[str, Any]] = None


class RunFinishRequest(RunHeartbeatRequest):
    status: Literal["finished", "failed", "interrupted"] = "finished"
    error_message: Optional[str] = None


class RunResponse(BaseModel):
    id: str
    assignment_id: Optional[str]
    task_id: Optional[str]
    dataset_name: str
    status: str
    started_at: datetime
    stopped_at: Optional[datetime] = None
    saved_episodes: int
    total_frames: Optional[int] = None
    fps: Optional[int] = None
    duration_seconds: int
    error_message: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None
    client_info: Optional[dict[str, Any]] = None
    task_params: Optional[dict[str, Any]] = None

    model_config = {"from_attributes": True}


class AdminProgressItem(AssignmentResponse):
    user_nickname: Optional[str] = None


def _assignment_response(assignment: CollectionAssignment, db: Session) -> AssignmentResponse:
    runs = db.query(CollectionRun).filter(CollectionRun.assignment_id == assignment.id).all()
    completed = sum(run.duration_seconds or 0 for run in runs if _run_status(run) != "failed")
    active_run = next((run for run in runs if _run_status(run) == "active"), None)
    return AssignmentResponse(
        id=str(assignment.id),
        user_id=str(assignment.user_id) if assignment.user_id else None,
        phone=assignment.phone,
        task_id=str(assignment.task_id),
        task_name=assignment.task.name,
        target_date=assignment.target_date,
        target_seconds=assignment.target_seconds,
        completed_seconds=completed,
        active_run_id=str(active_run.id) if active_run else None,
        is_active=assignment.is_active,
        task_params=_task_payload(assignment.task),
    )


def _run_response(run: CollectionRun) -> RunResponse:
    return RunResponse(
        id=str(run.id),
        assignment_id=str(run.assignment_id) if run.assignment_id else None,
        task_id=str(run.task_id) if run.task_id else None,
        dataset_name=run.dataset_name,
        status=_run_status(run),
        started_at=run.started_at,
        stopped_at=run.stopped_at,
        saved_episodes=run.saved_episodes,
        total_frames=run.total_frames,
        fps=run.fps,
        duration_seconds=run.duration_seconds,
        error_message=run.error_message,
        metadata=_json_loads(run.metadata_json),
        client_info=_json_loads(run.client_info_json),
        task_params=_task_payload(run.task) if run.task else None,
    )


def _bind_assignment_to_user(assignment: CollectionAssignment, user: User) -> bool:
    if assignment.user_id == user.id:
        return False
    assignment.user_id = user.id
    return True


@router.get("/my/assignments", response_model=list[AssignmentResponse])
def my_assignments(
    target_date: date | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    target_date = target_date or _today()
    assignments = (
        db.query(CollectionAssignment)
        .join(CollectionTask)
        .filter(
            CollectionAssignment.phone == current_user.phone,
            CollectionAssignment.target_date == target_date,
            CollectionAssignment.is_active == True,
            CollectionTask.is_active == True,
        )
        .order_by(CollectionTask.name.asc())
        .all()
    )
    changed = any(_bind_assignment_to_user(assignment, current_user) for assignment in assignments)
    if changed:
        db.commit()
        for assignment in assignments:
            db.refresh(assignment)
    return [_assignment_response(assignment, db) for assignment in assignments]


@router.post("/runs/start", response_model=RunResponse)
def start_run(
    body: RunStartRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db.query(User.id).filter(User.id == current_user.id).with_for_update().one()
    assignment = (
        db.query(CollectionAssignment)
        .filter(
            CollectionAssignment.id == body.assignment_id,
            CollectionAssignment.phone == current_user.phone,
            CollectionAssignment.target_date == _today(),
            CollectionAssignment.is_active == True,
        )
        .first()
    )
    if not assignment or not assignment.task or not assignment.task.is_active:
        raise HTTPException(status_code=404, detail="任务分配不存在或不可用")

    active = (
        db.query(CollectionRun)
        .filter(
            CollectionRun.user_id == current_user.id,
            CollectionRun.status == CollectionRunStatus.active,
        )
        .first()
    )
    if active:
        raise HTTPException(status_code=409, detail="当前用户已有进行中的采集")

    _bind_assignment_to_user(assignment, current_user)
    run_id = str(uuid.uuid4())
    dataset_name = body.dataset_name or f"{assignment.task.dataset_prefix}_{assignment.target_date:%Y%m%d}_{run_id[:8]}"
    run = CollectionRun(
        id=run_id,
        user_id=current_user.id,
        assignment_id=assignment.id,
        task_id=assignment.task_id,
        dataset_name=dataset_name,
        status=CollectionRunStatus.active,
        last_heartbeat_at=datetime.utcnow(),
        fps=assignment.task.fps,
        metadata_json=_json_dumps(body.metadata),
        client_info_json=_json_dumps(body.client_info),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return _run_response(run)


@router.post("/runs/{run_id}/heartbeat", response_model=RunResponse)
def heartbeat_run(
    run_id: str,
    body: RunHeartbeatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = (
        db.query(CollectionRun)
        .filter(
            CollectionRun.id == run_id,
            CollectionRun.user_id == current_user.id,
            CollectionRun.status == CollectionRunStatus.active,
        )
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="进行中的采集不存在")

    _update_run_metrics(run, body)
    run.last_heartbeat_at = datetime.utcnow()
    db.commit()
    db.refresh(run)
    return _run_response(run)


@router.post("/runs/{run_id}/finish", response_model=RunResponse)
def finish_run(
    run_id: str,
    body: RunFinishRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = (
        db.query(CollectionRun)
        .filter(
            CollectionRun.id == run_id,
            CollectionRun.user_id == current_user.id,
            CollectionRun.status == CollectionRunStatus.active,
        )
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="进行中的采集不存在")

    _update_run_metrics(run, body)
    run.status = CollectionRunStatus(body.status)
    run.stopped_at = datetime.utcnow()
    run.last_heartbeat_at = run.stopped_at
    run.error_message = body.error_message
    db.commit()
    db.refresh(run)
    return _run_response(run)


def _update_run_metrics(run: CollectionRun, body: RunHeartbeatRequest) -> None:
    if body.saved_episodes is not None:
        run.saved_episodes = max(body.saved_episodes, 0)
    if body.total_frames is not None:
        run.total_frames = max(body.total_frames, 0)
    if body.fps is not None:
        run.fps = max(body.fps, 0)
    if body.metadata is not None:
        run.metadata_json = _json_dumps(body.metadata)
    if body.client_info is not None:
        run.client_info_json = _json_dumps(body.client_info)
    run.duration_seconds = _run_duration(
        total_frames=run.total_frames,
        fps=run.fps,
        duration_seconds=body.duration_seconds,
        saved_episodes=run.saved_episodes,
        episode_time_s=run.task.episode_time_s if run.task else None,
    )


@router.get("/admin/tasks", response_model=list[CollectionTaskResponse])
def admin_list_tasks(
    include_inactive: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_admin(current_user)
    query = db.query(CollectionTask)
    if not include_inactive:
        query = query.filter(CollectionTask.is_active == True)
    return query.order_by(CollectionTask.created_at.desc()).all()


@router.post("/admin/tasks", response_model=CollectionTaskResponse)
def admin_create_task(
    body: CollectionTaskCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_admin(current_user)
    task = CollectionTask(**body.model_dump(), created_by_id=current_user.id)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@router.patch("/admin/tasks/{task_id}", response_model=CollectionTaskResponse)
def admin_update_task(
    task_id: str,
    body: CollectionTaskUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_admin(current_user)
    task = db.query(CollectionTask).filter(CollectionTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    for key, value in body.model_dump(exclude_unset=True).items():
        if isinstance(value, str):
            value = value.strip()
        setattr(task, key, value)
    db.commit()
    db.refresh(task)
    return task


@router.post("/admin/assignments", response_model=AssignmentResponse)
def admin_upsert_assignment(
    body: AssignmentCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_admin(current_user)
    task = db.query(CollectionTask).filter(CollectionTask.id == body.task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    user = db.query(User).filter(User.phone == body.phone).first()
    assignment = (
        db.query(CollectionAssignment)
        .filter(
            CollectionAssignment.phone == body.phone,
            CollectionAssignment.task_id == task.id,
            CollectionAssignment.target_date == body.target_date,
        )
        .first()
    )
    if assignment:
        assignment.user_id = user.id if user else None
        assignment.target_seconds = body.target_seconds
        assignment.is_active = body.is_active
    else:
        assignment = CollectionAssignment(
            phone=body.phone,
            user_id=user.id if user else None,
            task_id=task.id,
            target_date=body.target_date,
            target_seconds=body.target_seconds,
            is_active=body.is_active,
            created_by_id=current_user.id,
        )
        db.add(assignment)
    db.commit()
    db.refresh(assignment)
    return _assignment_response(assignment, db)


@router.get("/admin/progress", response_model=list[AdminProgressItem])
def admin_progress(
    target_date: date | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_admin(current_user)
    query = db.query(CollectionAssignment)
    if target_date is not None:
        query = query.filter(CollectionAssignment.target_date == target_date)
    assignments = query.order_by(CollectionAssignment.target_date.desc(), CollectionAssignment.created_at.desc()).all()
    items: list[AdminProgressItem] = []
    for assignment in assignments:
        payload = _assignment_response(assignment, db).model_dump()
        payload["user_nickname"] = assignment.user.nickname if assignment.user else None
        items.append(AdminProgressItem(**payload))
    return items
