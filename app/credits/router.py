from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.credits.payments import create_payment_qr, parse_wechat_notification, verify_alipay_notification
from app.credits.service import (
    CreditError,
    ensure_account,
    ensure_user_initial_accounts,
    mark_payment_order_paid,
    require_account_access,
)
from app.database import get_db
from app.deps import get_current_user
from app.models import (
    CreditAccount,
    CreditAccountType,
    CreditLedgerEntry,
    Dataset,
    DatasetPrice,
    DatasetPriceStatus,
    PaymentOrder,
    PaymentProvider,
    PlatformRole,
    RechargePackage,
    User,
)
from app.organization_access import current_membership

router = APIRouter(prefix="/credits", tags=["credits"])
payments_router = APIRouter(prefix="/payments", tags=["payments"])


class CreditAccountResponse(BaseModel):
    id: str
    org_id: str | None
    user_id: str
    account_type: str
    available_balance: int
    held_balance: int
    status: str


class LedgerEntryResponse(BaseModel):
    id: str
    account_id: str
    entry_type: str
    available_delta: int
    held_delta: int
    available_balance_after: int
    held_balance_after: int
    source_type: str
    source_id: str
    created_at: datetime | None


class RechargePackageResponse(BaseModel):
    id: str
    account_type: str
    name: str
    fiat_currency: str
    fiat_amount: int
    credit_amount: int


class PaymentOrderCreateRequest(BaseModel):
    account_id: str
    package_id: str
    provider: Literal["wechat", "alipay"]


class PaymentOrderResponse(BaseModel):
    id: str
    account_id: str
    package_id: str | None
    provider: str
    merchant_order_no: str
    provider_order_id: str | None
    fiat_currency: str
    fiat_amount: int
    credit_amount: int
    status: str
    qr_code_url: str | None
    paid_at: datetime | None
    expires_at: datetime | None


class DatasetPriceUpsertRequest(BaseModel):
    dataset_id: str
    credit_amount: int

    @field_validator("credit_amount")
    @classmethod
    def validate_credit_amount(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("credit_amount 必须大于 0")
        return value


class DatasetPriceResponse(BaseModel):
    id: str
    dataset_id: str
    credit_amount: int
    status: str


@router.get("/accounts", response_model=list[CreditAccountResponse])
def list_credit_accounts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ensure_user_initial_accounts(db, current_user)
    membership = current_membership(db, current_user)
    if membership is not None:
        for account_type in (CreditAccountType.data, CreditAccountType.training):
            ensure_account(
                db,
                user_id=str(current_user.id),
                account_type=account_type,
                org_id=str(membership.org_id),
                initial_credit=0,
            )
    db.commit()
    accounts = (
        db.query(CreditAccount)
        .filter(CreditAccount.user_id == current_user.id)
        .order_by(CreditAccount.org_id.asc(), CreditAccount.account_type.asc())
        .all()
    )
    return [_account_response(item) for item in accounts]


@router.get("/ledger", response_model=list[LedgerEntryResponse])
def list_ledger_entries(
    account_id: str,
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        require_account_access(db, account_id=account_id, user=current_user)
    except CreditError as exc:
        raise exc.to_http() from exc
    entries = (
        db.query(CreditLedgerEntry)
        .filter(CreditLedgerEntry.account_id == account_id)
        .order_by(CreditLedgerEntry.created_at.desc())
        .limit(limit)
        .all()
    )
    return [_ledger_response(item) for item in entries]


@router.get("/recharge-packages", response_model=list[RechargePackageResponse])
def list_recharge_packages(
    account_type: Literal["data", "training"],
    db: Session = Depends(get_db),
):
    packages = (
        db.query(RechargePackage)
        .filter(
            RechargePackage.account_type == CreditAccountType(account_type),
            RechargePackage.is_active == True,
        )
        .order_by(RechargePackage.sort_order.asc(), RechargePackage.credit_amount.asc())
        .all()
    )
    return [_package_response(item) for item in packages]


@router.post("/payment-orders", response_model=PaymentOrderResponse, status_code=status.HTTP_201_CREATED)
def create_order(
    body: PaymentOrderCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    package = db.query(RechargePackage).filter(
        RechargePackage.id == body.package_id,
        RechargePackage.is_active == True,
    ).first()
    if package is None:
        raise HTTPException(status_code=404, detail="充值套餐不存在")
    try:
        account = require_account_access(
            db,
            account_id=body.account_id,
            user=current_user,
            account_type=package.account_type,
        )
    except CreditError as exc:
        raise exc.to_http() from exc
    order = PaymentOrder(
        id=str(uuid4()),
        account_id=account.id,
        package_id=package.id,
        merchant_order_no=uuid4().hex,
        provider=PaymentProvider(body.provider),
        fiat_currency=package.fiat_currency,
        fiat_amount=package.fiat_amount,
        credit_amount=package.credit_amount,
        expires_at=datetime.utcnow() + timedelta(minutes=15),
    )
    db.add(order)
    db.flush()
    qr_code_url, provider_payload = create_payment_qr(order)
    order.qr_code_url = qr_code_url
    order.provider_payload_json = json.dumps(provider_payload, ensure_ascii=False)
    db.commit()
    db.refresh(order)
    return _order_response(order)


@router.get("/payment-orders/{order_id}", response_model=PaymentOrderResponse)
def get_order(
    order_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    order = db.query(PaymentOrder).filter(PaymentOrder.id == order_id).first()
    if order is None:
        raise HTTPException(status_code=404, detail="充值订单不存在")
    try:
        require_account_access(db, account_id=str(order.account_id), user=current_user)
    except CreditError as exc:
        raise exc.to_http() from exc
    return _order_response(order)


@router.post("/dataset-prices", response_model=DatasetPriceResponse)
def upsert_dataset_price(
    body: DatasetPriceUpsertRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.platform_role != PlatformRole.system_admin:
        raise HTTPException(status_code=403, detail="只有系统管理员可以设置数据售价")
    dataset = db.query(Dataset).filter(Dataset.id == body.dataset_id).first()
    if dataset is None:
        raise HTTPException(status_code=404, detail="数据集不存在")
    price = db.query(DatasetPrice).filter(DatasetPrice.dataset_id == body.dataset_id).first()
    if price is None:
        price = DatasetPrice(
            id=str(uuid4()),
            dataset_id=body.dataset_id,
            credit_amount=body.credit_amount,
            status=DatasetPriceStatus.active,
            created_by_user_id=current_user.id,
        )
        db.add(price)
    else:
        price.credit_amount = body.credit_amount
        price.status = DatasetPriceStatus.active
        price.created_by_user_id = current_user.id
    db.commit()
    db.refresh(price)
    return _dataset_price_response(price)


@payments_router.post("/wechat/notify")
async def wechat_notify(request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    payload = parse_wechat_notification(dict(request.headers), body)
    trade_state = payload.get("trade_state") or payload.get("status") or "SUCCESS"
    if trade_state != "SUCCESS":
        return {"code": "SUCCESS", "message": "ignored"}
    out_trade_no = str(payload.get("out_trade_no") or payload.get("merchant_order_no") or "")
    transaction_id = str(payload.get("transaction_id") or payload.get("provider_order_id") or out_trade_no)
    amount = payload.get("amount") or {}
    paid_amount = int(amount.get("total") if isinstance(amount, dict) else payload.get("total") or 0)
    try:
        mark_payment_order_paid(
            db,
            merchant_order_no=out_trade_no,
            provider_order_id=transaction_id,
            paid_amount=paid_amount,
        )
    except CreditError as exc:
        raise exc.to_http() from exc
    db.commit()
    return {"code": "SUCCESS", "message": "成功"}


@payments_router.post("/alipay/notify", response_class=PlainTextResponse)
async def alipay_notify(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    payload = verify_alipay_notification({key: str(value) for key, value in form.items()})
    trade_status = payload.get("trade_status") or "TRADE_SUCCESS"
    if trade_status not in {"TRADE_SUCCESS", "TRADE_FINISHED"}:
        return "success"
    out_trade_no = str(payload.get("out_trade_no") or "")
    trade_no = str(payload.get("trade_no") or out_trade_no)
    paid_amount = int(Decimal(str(payload.get("total_amount") or "0")) * 100)
    try:
        mark_payment_order_paid(
            db,
            merchant_order_no=out_trade_no,
            provider_order_id=trade_no,
            paid_amount=paid_amount,
        )
    except CreditError as exc:
        raise exc.to_http() from exc
    db.commit()
    return "success"


def _account_response(account: CreditAccount) -> CreditAccountResponse:
    return CreditAccountResponse(
        id=str(account.id),
        org_id=str(account.org_id) if account.org_id else None,
        user_id=str(account.user_id),
        account_type=_enum_value(account.account_type),
        available_balance=int(account.available_balance),
        held_balance=int(account.held_balance),
        status=_enum_value(account.status),
    )


def _ledger_response(entry: CreditLedgerEntry) -> LedgerEntryResponse:
    return LedgerEntryResponse(
        id=str(entry.id),
        account_id=str(entry.account_id),
        entry_type=_enum_value(entry.entry_type),
        available_delta=int(entry.available_delta),
        held_delta=int(entry.held_delta),
        available_balance_after=int(entry.available_balance_after),
        held_balance_after=int(entry.held_balance_after),
        source_type=entry.source_type,
        source_id=entry.source_id,
        created_at=entry.created_at,
    )


def _package_response(package: RechargePackage) -> RechargePackageResponse:
    return RechargePackageResponse(
        id=str(package.id),
        account_type=_enum_value(package.account_type),
        name=package.name,
        fiat_currency=package.fiat_currency,
        fiat_amount=int(package.fiat_amount),
        credit_amount=int(package.credit_amount),
    )


def _order_response(order: PaymentOrder) -> PaymentOrderResponse:
    return PaymentOrderResponse(
        id=str(order.id),
        account_id=str(order.account_id),
        package_id=str(order.package_id) if order.package_id else None,
        provider=_enum_value(order.provider),
        merchant_order_no=order.merchant_order_no,
        provider_order_id=order.provider_order_id,
        fiat_currency=order.fiat_currency,
        fiat_amount=int(order.fiat_amount),
        credit_amount=int(order.credit_amount),
        status=_enum_value(order.status),
        qr_code_url=order.qr_code_url,
        paid_at=order.paid_at,
        expires_at=order.expires_at,
    )


def _dataset_price_response(price: DatasetPrice) -> DatasetPriceResponse:
    return DatasetPriceResponse(
        id=str(price.id),
        dataset_id=str(price.dataset_id),
        credit_amount=int(price.credit_amount),
        status=_enum_value(price.status),
    )


def _enum_value(value) -> str:
    return value.value if hasattr(value, "value") else str(value)
