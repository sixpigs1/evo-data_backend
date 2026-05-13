from __future__ import annotations

import json
import math
from datetime import datetime
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import (
    CollectionRunUpload,
    Contribution,
    CreditAccount,
    CreditAccountStatus,
    CreditAccountType,
    CreditLedgerEntry,
    CreditLedgerEntryType,
    CreditPriceRule,
    Dataset,
    DatasetPrice,
    DatasetPriceStatus,
    DatasetPurchaseGrant,
    DatasetPurchaseGrantStatus,
    Membership,
    MembershipStatus,
    PaymentOrder,
    PaymentOrderStatus,
    PlatformRole,
    ResourceUsageRecord,
    ResourceUsageStatus,
    Upload,
    UploadRewardGrant,
    UploadRewardGrantStatus,
    User,
)

PERSONAL_ORG_SCOPE = "__personal__"
INITIAL_CREDIT_AMOUNT = 100
UPLOAD_REWARD_AMOUNT = 100
TRAINING_RESOURCE_TYPE = "remote_training"
TRAINING_UNIT = "gpu_hour"


class CreditError(RuntimeError):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail

    def to_http(self) -> HTTPException:
        return HTTPException(status_code=self.status_code, detail=self.detail)


def org_scope_key(org_id: str | None) -> str:
    return str(org_id) if org_id else PERSONAL_ORG_SCOPE


def ensure_user_initial_accounts(db: Session, user: User) -> None:
    for account_type in (CreditAccountType.data, CreditAccountType.training):
        ensure_account(
            db,
            user_id=str(user.id),
            account_type=account_type,
            org_id=None,
            initial_credit=INITIAL_CREDIT_AMOUNT,
        )


def ensure_account(
    db: Session,
    *,
    user_id: str,
    account_type: CreditAccountType,
    org_id: str | None,
    initial_credit: int = 0,
) -> CreditAccount:
    scope_key = org_scope_key(org_id)
    account = (
        db.query(CreditAccount)
        .filter(
            CreditAccount.user_id == user_id,
            CreditAccount.account_type == account_type,
            CreditAccount.org_scope_key == scope_key,
        )
        .first()
    )
    if account is not None:
        return account

    account = CreditAccount(
        id=str(uuid4()),
        user_id=user_id,
        org_id=org_id,
        account_type=account_type,
        org_scope_key=scope_key,
        available_balance=0,
        held_balance=0,
        status=CreditAccountStatus.active,
        version=0,
    )
    db.add(account)
    db.flush()
    if initial_credit:
        apply_entry(
            db,
            account=account,
            entry_type=CreditLedgerEntryType.initial_grant,
            available_delta=initial_credit,
            held_delta=0,
            source_type="system_initial_grant",
            source_id=f"{account.id}:initial",
        )
    return account


def require_account_access(
    db: Session,
    *,
    account_id: str,
    user: User,
    account_type: CreditAccountType | None = None,
) -> CreditAccount:
    account = db.query(CreditAccount).filter(CreditAccount.id == account_id).first()
    if account is None:
        raise CreditError(404, "积分账户不存在")
    if account_type is not None and account.account_type != account_type:
        raise CreditError(400, "积分账户类型不匹配")
    if account.status != CreditAccountStatus.active:
        raise CreditError(409, "积分账户不可用")
    if str(account.user_id) == str(user.id):
        return account
    if account.org_id and _has_active_org_membership(db, user, str(account.org_id)):
        return account
    raise CreditError(403, "无权访问此积分账户")


def apply_entry(
    db: Session,
    *,
    account: CreditAccount,
    entry_type: CreditLedgerEntryType,
    available_delta: int,
    held_delta: int,
    source_type: str,
    source_id: str,
) -> CreditLedgerEntry:
    existing = (
        db.query(CreditLedgerEntry)
        .filter(
            CreditLedgerEntry.account_id == account.id,
            CreditLedgerEntry.entry_type == entry_type,
            CreditLedgerEntry.source_type == source_type,
            CreditLedgerEntry.source_id == source_id,
        )
        .first()
    )
    if existing is not None:
        return existing

    locked = (
        db.query(CreditAccount)
        .filter(CreditAccount.id == account.id)
        .with_for_update()
        .one()
    )
    next_available = int(locked.available_balance) + int(available_delta)
    next_held = int(locked.held_balance) + int(held_delta)
    if next_available < 0:
        raise CreditError(409, "可用积分不足")
    if next_held < 0:
        raise CreditError(409, "冻结积分不足")

    locked.available_balance = next_available
    locked.held_balance = next_held
    locked.version = int(locked.version or 0) + 1
    entry = CreditLedgerEntry(
        id=str(uuid4()),
        account_id=locked.id,
        entry_type=entry_type,
        available_delta=available_delta,
        held_delta=held_delta,
        available_balance_after=next_available,
        held_balance_after=next_held,
        source_type=source_type,
        source_id=source_id,
    )
    db.add(entry)
    db.flush()
    account.available_balance = locked.available_balance
    account.held_balance = locked.held_balance
    account.version = locked.version
    return entry


def hold_credits(
    db: Session,
    *,
    account: CreditAccount,
    amount: int,
    source_type: str,
    source_id: str,
) -> CreditLedgerEntry:
    return apply_entry(
        db,
        account=account,
        entry_type=CreditLedgerEntryType.training_hold,
        available_delta=-amount,
        held_delta=amount,
        source_type=source_type,
        source_id=source_id,
    )


def release_credits(
    db: Session,
    *,
    account: CreditAccount,
    amount: int,
    source_type: str,
    source_id: str,
) -> CreditLedgerEntry:
    return apply_entry(
        db,
        account=account,
        entry_type=CreditLedgerEntryType.training_release,
        available_delta=amount,
        held_delta=-amount,
        source_type=source_type,
        source_id=source_id,
    )


def settle_held_credits(
    db: Session,
    *,
    account: CreditAccount,
    held_amount: int,
    actual_amount: int,
    source_type: str,
    source_id: str,
) -> CreditLedgerEntry:
    refund = max(0, held_amount - actual_amount)
    extra_charge = max(0, actual_amount - held_amount)
    return apply_entry(
        db,
        account=account,
        entry_type=CreditLedgerEntryType.training_settle,
        available_delta=refund - extra_charge,
        held_delta=-held_amount,
        source_type=source_type,
        source_id=source_id,
    )


def credit_recharge(
    db: Session,
    *,
    account: CreditAccount,
    amount: int,
    source_type: str,
    source_id: str,
) -> CreditLedgerEntry:
    return apply_entry(
        db,
        account=account,
        entry_type=CreditLedgerEntryType.recharge,
        available_delta=amount,
        held_delta=0,
        source_type=source_type,
        source_id=source_id,
    )


def mark_payment_order_paid(
    db: Session,
    *,
    merchant_order_no: str,
    provider_order_id: str,
    paid_amount: int,
) -> PaymentOrder:
    if provider_order_id:
        existing_provider_order = (
            db.query(PaymentOrder)
            .filter(PaymentOrder.provider_order_id == provider_order_id)
            .with_for_update()
            .first()
        )
        if existing_provider_order is not None:
            if existing_provider_order.merchant_order_no == merchant_order_no:
                return existing_provider_order
            raise CreditError(409, "支付渠道订单已绑定其他充值订单")

    order = (
        db.query(PaymentOrder)
        .filter(PaymentOrder.merchant_order_no == merchant_order_no)
        .with_for_update()
        .first()
    )
    if order is None:
        raise CreditError(404, "充值订单不存在")
    if int(order.fiat_amount) != int(paid_amount):
        raise CreditError(409, "支付金额与订单金额不一致")
    if order.status == PaymentOrderStatus.paid:
        return order
    if order.status != PaymentOrderStatus.created:
        raise CreditError(409, "充值订单状态不可支付")
    account = db.query(CreditAccount).filter(CreditAccount.id == order.account_id).one()
    entry = credit_recharge(
        db,
        account=account,
        amount=int(order.credit_amount),
        source_type="payment_order",
        source_id=order.id,
    )
    order.status = PaymentOrderStatus.paid
    order.provider_order_id = provider_order_id
    order.ledger_entry_id = entry.id
    order.paid_at = datetime.utcnow()
    return order


def debit_dataset_purchase(
    db: Session,
    *,
    account: CreditAccount,
    amount: int,
    source_type: str,
    source_id: str,
) -> CreditLedgerEntry:
    return apply_entry(
        db,
        account=account,
        entry_type=CreditLedgerEntryType.dataset_purchase,
        available_delta=-amount,
        held_delta=0,
        source_type=source_type,
        source_id=source_id,
    )


def reward_upload(
    db: Session,
    *,
    upload: Upload,
    dataset: Dataset,
) -> UploadRewardGrant:
    existing = db.query(UploadRewardGrant).filter(UploadRewardGrant.upload_id == upload.id).first()
    if existing is not None:
        return existing

    org_id = _collection_upload_org_id(db, str(upload.id))
    account = ensure_account(
        db,
        user_id=str(upload.user_id),
        account_type=CreditAccountType.data,
        org_id=org_id,
        initial_credit=0,
    )
    grant = UploadRewardGrant(
        id=str(uuid4()),
        account_id=account.id,
        upload_id=upload.id,
        dataset_id=dataset.id,
        base_credit=UPLOAD_REWARD_AMOUNT,
        factor_json=json.dumps({"base": 1}, separators=(",", ":")),
        final_credit=UPLOAD_REWARD_AMOUNT,
        status=UploadRewardGrantStatus.approved,
        reviewed_at=datetime.utcnow(),
    )
    db.add(grant)
    db.flush()
    entry = apply_entry(
        db,
        account=account,
        entry_type=CreditLedgerEntryType.upload_reward,
        available_delta=UPLOAD_REWARD_AMOUNT,
        held_delta=0,
        source_type="upload_reward",
        source_id=grant.id,
    )
    grant.status = UploadRewardGrantStatus.rewarded
    grant.ledger_entry_id = entry.id
    grant.rewarded_at = datetime.utcnow()
    return grant


def active_dataset_price(db: Session, dataset_id: str) -> DatasetPrice | None:
    return (
        db.query(DatasetPrice)
        .filter(
            DatasetPrice.dataset_id == dataset_id,
            DatasetPrice.status == DatasetPriceStatus.active,
        )
        .first()
    )


def purchase_dataset(
    db: Session,
    *,
    dataset: Dataset,
    account: CreditAccount,
    user: User,
) -> DatasetPurchaseGrant:
    existing = (
        db.query(DatasetPurchaseGrant)
        .filter(
            DatasetPurchaseGrant.dataset_id == dataset.id,
            DatasetPurchaseGrant.account_id == account.id,
            DatasetPurchaseGrant.status == DatasetPurchaseGrantStatus.active,
        )
        .first()
    )
    if existing is not None:
        return existing

    price = active_dataset_price(db, str(dataset.id))
    if price is None:
        raise CreditError(404, "数据集未设置售价")
    usage = ResourceUsageRecord(
        id=str(uuid4()),
        account_id=account.id,
        org_id=account.org_id,
        user_id=user.id,
        resource_type="dataset_access",
        resource_id=str(dataset.id),
        quantity=1,
        unit="dataset_access",
        credit_amount=int(price.credit_amount),
        status=ResourceUsageStatus.pending,
        started_at=datetime.utcnow(),
        ended_at=datetime.utcnow(),
    )
    db.add(usage)
    db.flush()
    entry = debit_dataset_purchase(
        db,
        account=account,
        amount=int(price.credit_amount),
        source_type="dataset_purchase",
        source_id=usage.id,
    )
    usage.ledger_entry_id = entry.id
    usage.status = ResourceUsageStatus.settled
    grant = DatasetPurchaseGrant(
        id=str(uuid4()),
        dataset_id=dataset.id,
        account_id=account.id,
        user_id=user.id,
        org_id=account.org_id,
        resource_usage_record_id=usage.id,
        source_type="purchase",
        source_id=usage.id,
        status=DatasetPurchaseGrantStatus.active,
    )
    db.add(grant)
    db.flush()
    return grant


def has_dataset_access(db: Session, *, dataset: Dataset, user: User | None) -> bool:
    if user is None:
        return False
    if str(dataset.owner_id) == str(user.id):
        return True
    if user.platform_role == PlatformRole.system_admin:
        return True
    if (
        db.query(DatasetPurchaseGrant)
        .filter(
            DatasetPurchaseGrant.dataset_id == dataset.id,
            DatasetPurchaseGrant.user_id == user.id,
            DatasetPurchaseGrant.status == DatasetPurchaseGrantStatus.active,
        )
        .first()
        is not None
    ):
        return True
    active_org_ids = [
        str(item.org_id)
        for item in db.query(Membership)
        .filter(
            Membership.user_id == user.id,
            Membership.status == MembershipStatus.active,
        )
        .all()
    ]
    if not active_org_ids:
        return False
    return (
        db.query(DatasetPurchaseGrant)
        .filter(
            DatasetPurchaseGrant.dataset_id == dataset.id,
            DatasetPurchaseGrant.org_id.in_(active_org_ids),
            DatasetPurchaseGrant.status == DatasetPurchaseGrantStatus.active,
        )
        .first()
        is not None
    )


def training_rate(db: Session, gpu_type: str | None) -> int:
    keys = [gpu_type.strip() if gpu_type else "", "default"]
    for key in keys:
        if not key:
            continue
        rule = (
            db.query(CreditPriceRule)
            .filter(
                CreditPriceRule.resource_type == TRAINING_RESOURCE_TYPE,
                CreditPriceRule.resource_key == key,
                CreditPriceRule.unit == TRAINING_UNIT,
                CreditPriceRule.is_active == True,
            )
            .first()
        )
        if rule is not None:
            return int(rule.credit_amount)
    return 10


def estimate_training_hold(*, gpu_count: int, seconds: int, rate_per_gpu_hour: int) -> int:
    safe_gpu_count = max(1, int(gpu_count))
    safe_seconds = max(0, int(seconds))
    return int(math.ceil(safe_gpu_count * safe_seconds * int(rate_per_gpu_hour) / 3600))


def _collection_upload_org_id(db: Session, upload_id: str) -> str | None:
    collection_upload = (
        db.query(CollectionRunUpload)
        .filter(CollectionRunUpload.upload_id == upload_id)
        .first()
    )
    if collection_upload is None or collection_upload.run is None:
        return None
    return str(collection_upload.run.org_id)


def _has_active_org_membership(db: Session, user: User, org_id: str) -> bool:
    return (
        db.query(Membership)
        .filter(
            Membership.user_id == user.id,
            Membership.org_id == org_id,
            Membership.status == MembershipStatus.active,
        )
        .first()
        is not None
    )
