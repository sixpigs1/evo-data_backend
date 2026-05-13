from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.credits.service import (
    ensure_account,
    ensure_user_initial_accounts,
    hold_credits,
    mark_payment_order_paid,
    purchase_dataset,
    release_credits,
    settle_held_credits,
)
from app.database import Base
from app.models import (
    CreditAccount,
    CreditAccountType,
    CreditLedgerEntry,
    CreditLedgerEntryType,
    Dataset,
    DatasetPrice,
    DatasetPurchaseGrant,
    PaymentOrder,
    PaymentOrderStatus,
    PaymentProvider,
    ResourceUsageRecord,
    User,
    UserStatus,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def add_user(db, user_id: str = "user-1") -> User:
    phone_suffix = sum((index + 1) * ord(char) for index, char in enumerate(user_id)) % 100_000_000
    user = User(id=user_id, phone=f"138{phone_suffix:08d}", status=UserStatus.active)
    db.add(user)
    db.flush()
    return user


def test_initial_accounts_are_created_once(db):
    user = add_user(db)

    ensure_user_initial_accounts(db, user)
    ensure_user_initial_accounts(db, user)
    db.commit()

    accounts = db.query(CreditAccount).order_by(CreditAccount.account_type).all()
    assert len(accounts) == 2
    assert {account.account_type for account in accounts} == {CreditAccountType.data, CreditAccountType.training}
    assert all(account.available_balance == 100 for account in accounts)
    assert db.query(CreditLedgerEntry).filter(CreditLedgerEntry.entry_type == CreditLedgerEntryType.initial_grant).count() == 2


def test_training_hold_release_and_settle_updates_balances(db):
    user = add_user(db)
    account = ensure_account(
        db,
        user_id=str(user.id),
        account_type=CreditAccountType.training,
        org_id=None,
        initial_credit=100,
    )

    hold_credits(db, account=account, amount=30, source_type="remote_training", source_id="usage-1")
    release_credits(db, account=account, amount=10, source_type="remote_training_failed", source_id="usage-1")
    settle_held_credits(db, account=account, held_amount=20, actual_amount=15, source_type="remote_training", source_id="usage-1")

    db.refresh(account)
    assert account.available_balance == 85
    assert account.held_balance == 0


def test_payment_paid_callback_is_idempotent(db):
    user = add_user(db)
    account = ensure_account(
        db,
        user_id=str(user.id),
        account_type=CreditAccountType.data,
        org_id=None,
        initial_credit=100,
    )
    order = PaymentOrder(
        id=str(uuid4()),
        account_id=account.id,
        merchant_order_no="merchant-1",
        provider=PaymentProvider.wechat,
        fiat_currency="CNY",
        fiat_amount=5000,
        credit_amount=50,
        status=PaymentOrderStatus.created,
    )
    db.add(order)
    db.flush()

    mark_payment_order_paid(db, merchant_order_no="merchant-1", provider_order_id="provider-1", paid_amount=5000)
    mark_payment_order_paid(db, merchant_order_no="merchant-1", provider_order_id="provider-1", paid_amount=5000)

    db.refresh(account)
    assert account.available_balance == 150
    assert db.query(CreditLedgerEntry).filter(CreditLedgerEntry.entry_type == CreditLedgerEntryType.recharge).count() == 1


def test_dataset_purchase_is_idempotent(db):
    owner = add_user(db, "owner-1")
    buyer = add_user(db, "buyer-1")
    account = ensure_account(
        db,
        user_id=str(buyer.id),
        account_type=CreditAccountType.data,
        org_id=None,
        initial_credit=100,
    )
    dataset = Dataset(
        id="dataset-1",
        owner_id=owner.id,
        name="dataset",
        is_public=True,
    )
    db.add(dataset)
    db.add(DatasetPrice(id=str(uuid4()), dataset_id=dataset.id, credit_amount=25, created_by_user_id=owner.id))
    db.flush()

    first = purchase_dataset(db, dataset=dataset, account=account, user=buyer)
    second = purchase_dataset(db, dataset=dataset, account=account, user=buyer)

    db.refresh(account)
    assert first.id == second.id
    assert account.available_balance == 75
    assert db.query(DatasetPurchaseGrant).count() == 1
    assert db.query(ResourceUsageRecord).count() == 1
