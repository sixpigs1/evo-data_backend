from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.config import settings
from app.credits.service import (
    CreditError,
    estimate_training_hold,
    hold_credits,
    release_credits,
    require_account_access,
    settle_held_credits,
    training_rate,
)
from app.database import get_db
from app.deps import get_current_user
from app.models import (
    CreditAccount,
    CreditAccountType,
    RemoteTrainingJob,
    RemoteTrainingJobStatus,
    ResourceUsageRecord,
    ResourceUsageStatus,
    User,
)
from app.training.remote_connection import RemoteTrainingConnection

router = APIRouter(prefix="/train", tags=["training"])
_remote_training_connection = RemoteTrainingConnection(settings.REMOTE_TRAINING_HOST, settings.REMOTE_TRAINING_PORT)


class RemoteTrainStartRequest(BaseModel):
    username: str
    taskName: str = ""
    account_id: str | None = None
    datasetPath: str | None = None
    steps: int | None = None
    saveFreq: int | None = None
    gpuCount: int | None = None
    gpuType: str | None = None
    batchSize: int | None = None
    policyType: str | None = None
    emptyDocker: bool | None = None
    sleepT: int | None = None
    logFreq: int | None = None
    downloadAll: bool | None = None
    downloadList: str | None = None
    action: str


class TrainingEstimateResponse(BaseModel):
    account_id: str
    gpu_count: int
    gpu_type: str
    seconds: int
    rate_per_gpu_hour: int
    hold_credit: int
    available_balance: int
    held_balance: int
    enough_balance: bool


class TrainingEstimateRequest(BaseModel):
    account_id: str
    gpu_count: int = 1
    gpu_type: str = ""
    seconds: int = 0

    @field_validator("gpu_count")
    @classmethod
    def validate_gpu_count(cls, value: int) -> int:
        return max(1, value)

    @field_validator("seconds")
    @classmethod
    def validate_seconds(cls, value: int) -> int:
        return max(0, value)


class RemoteDownloadProgress:
    def __init__(self) -> None:
        self._items: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def start(self, download_id: str, total_bytes: int) -> None:
        async with self._lock:
            self._items[download_id] = {
                "downloadId": download_id,
                "downloadedBytes": 0,
                "totalBytes": total_bytes,
                "status": "downloading",
                "updatedAt": time.time(),
            }

    def update_now(self, download_id: str, downloaded_bytes: int) -> None:
        item = self._items.get(download_id)
        if item is None:
            return
        item["downloadedBytes"] = downloaded_bytes
        item["updatedAt"] = time.time()

    async def finish(self, download_id: str) -> None:
        async with self._lock:
            item = self._items.get(download_id)
            if item is None:
                return
            item["downloadedBytes"] = item.get("totalBytes") or item.get("downloadedBytes", 0)
            item["status"] = "completed"
            item["updatedAt"] = time.time()

    async def fail(self, download_id: str, message: str) -> None:
        async with self._lock:
            item = self._items.setdefault(download_id, {"downloadId": download_id, "downloadedBytes": 0, "totalBytes": 0})
            item["status"] = "failed"
            item["message"] = message
            item["updatedAt"] = time.time()

    async def snapshot(self, download_id: str) -> dict[str, Any]:
        async with self._lock:
            item = self._items.get(download_id)
            if item is None:
                return {"downloadId": download_id, "downloadedBytes": 0, "totalBytes": 0, "status": "unknown"}
            return dict(item)


_download_progress = RemoteDownloadProgress()


@router.post("/remote/estimate", response_model=TrainingEstimateResponse)
def estimate_remote_training(
    body: TrainingEstimateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        account = require_account_access(
            db,
            account_id=body.account_id,
            user=current_user,
            account_type=CreditAccountType.training,
        )
    except CreditError as exc:
        raise exc.to_http() from exc
    rate = training_rate(db, body.gpu_type)
    hold_credit = estimate_training_hold(
        gpu_count=body.gpu_count,
        seconds=body.seconds,
        rate_per_gpu_hour=rate,
    )
    return TrainingEstimateResponse(
        account_id=str(account.id),
        gpu_count=body.gpu_count,
        gpu_type=body.gpu_type or "default",
        seconds=body.seconds,
        rate_per_gpu_hour=rate,
        hold_credit=hold_credit,
        available_balance=int(account.available_balance),
        held_balance=int(account.held_balance),
        enough_balance=int(account.available_balance) >= hold_credit,
    )


@router.post("/remote/start", response_model=None)
async def remote_train_start(
    body: RemoteTrainStartRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Any:
    if body.action == "开始训练":
        return await _start_billed_training(body, current_user, db)
    if body.action in {"结束训练", "删除任务"}:
        response = await _remote_training_connection.request(_serialize_remote_request(body))
        _settle_training_if_needed(db, current_user, body.taskName)
        db.commit()
        return response
    return await _remote_training_connection.request(_serialize_remote_request(body))


@router.get("/remote/download", response_model=None)
async def remote_training_download(
    username: str,
    taskName: str,
    downloadId: str = "",
    downloadAll: bool = True,
    downloadList: str = "",
    expectedSize: int = 0,
    _current_user: User = Depends(get_current_user),
) -> Any:
    body = RemoteTrainStartRequest(
        username=username,
        taskName=taskName,
        action="结果下载",
        downloadAll=downloadAll,
        downloadList=downloadList,
    )
    total_bytes = max(0, expectedSize)
    if downloadId:
        await _download_progress.start(downloadId, total_bytes)
    filename_task = body.taskName.strip() or "remote-training-result"
    filename_scope = "all" if downloadAll else "selected"
    download = await _remote_training_connection.download(
        _serialize_remote_request(body),
        f"{filename_task}-{filename_scope}-result.tar",
        lambda downloaded: _download_progress.update_now(downloadId, downloaded) if downloadId else None,
    )
    if isinstance(download, dict):
        if downloadId:
            await _download_progress.fail(downloadId, str(download.get("message") or "download failed"))
        return download

    message = str(download.response.get("message") or "")

    async def tracked_chunks() -> Any:
        try:
            async for chunk in download.chunks:
                yield chunk
            if downloadId:
                await _download_progress.finish(downloadId)
        except Exception as exc:
            if downloadId:
                await _download_progress.fail(downloadId, str(exc))
            raise

    return StreamingResponse(
        tracked_chunks(),
        media_type=download.media_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(download.filename)}",
            "X-Remote-Training-Message": quote(message, safe=""),
            "X-Remote-Training-Size": str(total_bytes),
        },
    )


@router.get("/remote/download/progress")
async def remote_training_download_progress(
    downloadId: str,
    _current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return await _download_progress.snapshot(downloadId)


async def _start_billed_training(
    body: RemoteTrainStartRequest,
    current_user: User,
    db: Session,
) -> dict[str, Any]:
    if not body.account_id:
        raise HTTPException(status_code=400, detail="account_id is required")
    if not body.taskName:
        raise HTTPException(status_code=400, detail="taskName is required")
    try:
        account = require_account_access(
            db,
            account_id=body.account_id,
            user=current_user,
            account_type=CreditAccountType.training,
        )
        existing_job = (
            db.query(RemoteTrainingJob)
            .filter(
                RemoteTrainingJob.user_id == current_user.id,
                RemoteTrainingJob.task_name == body.taskName,
                RemoteTrainingJob.status.in_([RemoteTrainingJobStatus.held, RemoteTrainingJobStatus.running]),
            )
            .first()
        )
        if existing_job is not None:
            raise HTTPException(status_code=409, detail="同名远程训练任务已在计费中")
        rate = training_rate(db, body.gpuType)
        expected_seconds = int(body.sleepT or 0)
        hold_credit = estimate_training_hold(
            gpu_count=int(body.gpuCount or 1),
            seconds=expected_seconds,
            rate_per_gpu_hour=rate,
        )
        usage = ResourceUsageRecord(
            account_id=account.id,
            org_id=account.org_id,
            user_id=current_user.id,
            resource_type="remote_training",
            resource_id=body.taskName,
            quantity=max(1, int(body.gpuCount or 1)) * max(0, expected_seconds),
            unit="gpu_second",
            credit_amount=hold_credit,
            status=ResourceUsageStatus.pending,
            started_at=datetime.utcnow(),
        )
        db.add(usage)
        db.flush()
        entry = hold_credits(
            db,
            account=account,
            amount=hold_credit,
            source_type="remote_training",
            source_id=str(usage.id),
        )
        usage.ledger_entry_id = entry.id
        usage.status = ResourceUsageStatus.held
        job = RemoteTrainingJob(
            account_id=account.id,
            usage_record_id=usage.id,
            org_id=account.org_id,
            user_id=current_user.id,
            username=body.username,
            task_name=body.taskName,
            gpu_type=body.gpuType or "default",
            gpu_count=int(body.gpuCount or 1),
            expected_seconds=expected_seconds,
            hold_credit=hold_credit,
            status=RemoteTrainingJobStatus.held,
            request_json=json.dumps(body.model_dump(exclude_none=True), ensure_ascii=False),
            started_at=datetime.utcnow(),
        )
        db.add(job)
        db.commit()
    except CreditError as exc:
        db.rollback()
        raise exc.to_http() from exc

    try:
        response = await _remote_training_connection.request(_serialize_remote_request(body))
    except Exception:
        _fail_training_hold(db, str(job.id))
        db.commit()
        raise

    if response.get("message") == "create task success":
        job.status = RemoteTrainingJobStatus.running
        db.commit()
        response["billing"] = {
            "account_id": account.id,
            "usage_record_id": usage.id,
            "hold_credit": hold_credit,
            "rate_per_gpu_hour": rate,
        }
        return response

    _fail_training_hold(db, str(job.id))
    db.commit()
    response["billing"] = {
        "status": "released",
        "hold_credit": hold_credit,
    }
    return response


def _fail_training_hold(db: Session, job_id: str) -> None:
    job = db.query(RemoteTrainingJob).filter(RemoteTrainingJob.id == job_id).first()
    if job is None or job.status == RemoteTrainingJobStatus.failed:
        return
    account_id = job.account_id
    usage = db.query(ResourceUsageRecord).filter(ResourceUsageRecord.id == job.usage_record_id).first()
    credit_account = db.query(CreditAccount).filter(CreditAccount.id == account_id).first()
    if credit_account is not None and int(job.hold_credit) > 0:
        release_credits(
            db,
            account=credit_account,
            amount=int(job.hold_credit),
            source_type="remote_training_failed",
            source_id=str(usage.id if usage else job.id),
        )
    if usage is not None:
        usage.status = ResourceUsageStatus.failed
        usage.ended_at = datetime.utcnow()
    job.status = RemoteTrainingJobStatus.failed
    job.ended_at = datetime.utcnow()


def _settle_training_if_needed(db: Session, current_user: User, task_name: str) -> None:
    if not task_name:
        return
    job = (
        db.query(RemoteTrainingJob)
        .filter(
            RemoteTrainingJob.user_id == current_user.id,
            RemoteTrainingJob.task_name == task_name,
            RemoteTrainingJob.status.in_([RemoteTrainingJobStatus.held, RemoteTrainingJobStatus.running]),
        )
        .order_by(RemoteTrainingJob.created_at.desc())
        .first()
    )
    if job is None:
        return
    account = db.query(CreditAccount).filter(CreditAccount.id == job.account_id).first()
    usage = db.query(ResourceUsageRecord).filter(ResourceUsageRecord.id == job.usage_record_id).first()
    if account is None or usage is None:
        return
    ended_at = datetime.utcnow()
    started_at = job.started_at or usage.started_at or ended_at
    elapsed_seconds = max(0, int((ended_at - started_at).total_seconds()))
    billable_seconds = min(elapsed_seconds, int(job.expected_seconds or elapsed_seconds))
    rate = training_rate(db, job.gpu_type)
    actual_credit = estimate_training_hold(
        gpu_count=int(job.gpu_count or 1),
        seconds=billable_seconds,
        rate_per_gpu_hour=rate,
    )
    entry = settle_held_credits(
        db,
        account=account,
        held_amount=int(job.hold_credit),
        actual_amount=actual_credit,
        source_type="remote_training",
        source_id=str(usage.id),
    )
    usage.status = ResourceUsageStatus.settled
    usage.ended_at = ended_at
    usage.credit_amount = actual_credit
    usage.ledger_entry_id = entry.id
    job.status = RemoteTrainingJobStatus.settled
    job.ended_at = ended_at
    job.settled_credit = actual_credit


def _serialize_remote_request(body: RemoteTrainStartRequest) -> bytes:
    payload = body.model_dump(exclude_none=True, exclude={"account_id"})
    return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
