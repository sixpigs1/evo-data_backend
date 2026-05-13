"""add credit accounts, payments, purchases, and training billing

Revision ID: 010_credits_billing
Revises: 009_collection_run_uploads
Create Date: 2026-05-13
"""
from alembic import op
import sqlalchemy as sa


revision = "010_credits_billing"
down_revision = "009_collection_run_uploads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "credit_accounts",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("org_id", sa.CHAR(36), nullable=True),
        sa.Column("user_id", sa.CHAR(36), nullable=False),
        sa.Column("account_type", sa.Enum("data", "training", name="creditaccounttype"), nullable=False),
        sa.Column("org_scope_key", sa.String(64), nullable=False),
        sa.Column("available_balance", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("held_balance", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("status", sa.Enum("active", "frozen", "closed", name="creditaccountstatus"), server_default="active", nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "account_type", "org_scope_key", name="uq_credit_accounts_user_type_scope"),
    )
    op.create_index("ix_credit_accounts_org_id", "credit_accounts", ["org_id"])
    op.create_index("ix_credit_accounts_user_id", "credit_accounts", ["user_id"])
    op.create_index("ix_credit_accounts_org_user", "credit_accounts", ["org_id", "user_id"])

    op.create_table(
        "credit_ledger_entries",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("account_id", sa.CHAR(36), nullable=False),
        sa.Column(
            "entry_type",
            sa.Enum(
                "initial_grant",
                "recharge",
                "upload_reward",
                "dataset_purchase",
                "training_hold",
                "training_release",
                "training_settle",
                "manual_adjust",
                name="creditledgerentrytype",
            ),
            nullable=False,
        ),
        sa.Column("available_delta", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("held_delta", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("available_balance_after", sa.BigInteger(), nullable=False),
        sa.Column("held_balance_after", sa.BigInteger(), nullable=False),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("source_id", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["credit_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "entry_type", "source_type", "source_id", name="uq_credit_ledger_source"),
    )
    op.create_index("ix_credit_ledger_entries_account_id", "credit_ledger_entries", ["account_id"])
    op.create_index("ix_credit_ledger_account_created", "credit_ledger_entries", ["account_id", "created_at"])
    op.create_index("ix_credit_ledger_source", "credit_ledger_entries", ["source_type", "source_id"])

    op.create_table(
        "recharge_packages",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("account_type", sa.Enum("data", "training", name="rechargepackageaccounttype"), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("fiat_currency", sa.String(8), server_default="CNY", nullable=False),
        sa.Column("fiat_amount", sa.BigInteger(), nullable=False),
        sa.Column("credit_amount", sa.BigInteger(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_type", "credit_amount", name="uq_recharge_packages_type_amount"),
    )
    op.create_index("ix_recharge_packages_type_active", "recharge_packages", ["account_type", "is_active"])

    op.create_table(
        "payment_orders",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("account_id", sa.CHAR(36), nullable=False),
        sa.Column("package_id", sa.CHAR(36), nullable=True),
        sa.Column("merchant_order_no", sa.String(64), nullable=False),
        sa.Column("provider", sa.Enum("wechat", "alipay", "manual", name="paymentprovider"), nullable=False),
        sa.Column("provider_order_id", sa.String(128), nullable=True),
        sa.Column("fiat_currency", sa.String(8), server_default="CNY", nullable=False),
        sa.Column("fiat_amount", sa.BigInteger(), nullable=False),
        sa.Column("credit_amount", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.Enum("created", "paid", "failed", "closed", "refunded", name="paymentorderstatus"), server_default="created", nullable=False),
        sa.Column("ledger_entry_id", sa.CHAR(36), nullable=True),
        sa.Column("qr_code_url", sa.String(2048), nullable=True),
        sa.Column("provider_payload_json", sa.Text(), nullable=True),
        sa.Column("paid_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["credit_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ledger_entry_id"], ["credit_ledger_entries.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["package_id"], ["recharge_packages.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("merchant_order_no", name="uq_payment_orders_merchant_order_no"),
        sa.UniqueConstraint("provider", "provider_order_id", name="uq_payment_orders_provider_order"),
    )
    op.create_index("ix_payment_orders_account_id", "payment_orders", ["account_id"])
    op.create_index("ix_payment_orders_account_status", "payment_orders", ["account_id", "status"])

    op.create_table(
        "upload_reward_grants",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("account_id", sa.CHAR(36), nullable=False),
        sa.Column("upload_id", sa.CHAR(36), nullable=False),
        sa.Column("dataset_id", sa.CHAR(36), nullable=True),
        sa.Column("base_credit", sa.BigInteger(), server_default=sa.text("100"), nullable=False),
        sa.Column("factor_json", sa.Text(), nullable=True),
        sa.Column("final_credit", sa.BigInteger(), server_default=sa.text("100"), nullable=False),
        sa.Column("status", sa.Enum("pending_review", "approved", "rewarded", "rejected", "revoked", name="uploadrewardgrantstatus"), server_default="pending_review", nullable=False),
        sa.Column("ledger_entry_id", sa.CHAR(36), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("rewarded_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["credit_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["ledger_entry_id"], ["credit_ledger_entries.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["upload_id"], ["uploads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("upload_id", name="uq_upload_reward_grants_upload_id"),
    )
    op.create_index("ix_upload_reward_grants_account_id", "upload_reward_grants", ["account_id"])
    op.create_index("ix_upload_reward_grants_account_status", "upload_reward_grants", ["account_id", "status"])

    op.create_table(
        "resource_usage_records",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("account_id", sa.CHAR(36), nullable=False),
        sa.Column("org_id", sa.CHAR(36), nullable=True),
        sa.Column("user_id", sa.CHAR(36), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(128), nullable=False),
        sa.Column("quantity", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("unit", sa.String(32), nullable=False),
        sa.Column("credit_amount", sa.BigInteger(), nullable=False),
        sa.Column("ledger_entry_id", sa.CHAR(36), nullable=True),
        sa.Column("status", sa.Enum("pending", "held", "settled", "failed", "refunded", name="resourceusagestatus"), server_default="pending", nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["credit_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ledger_entry_id"], ["credit_ledger_entries.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_resource_usage_records_account_id", "resource_usage_records", ["account_id"])
    op.create_index("ix_resource_usage_records_org_id", "resource_usage_records", ["org_id"])
    op.create_index("ix_resource_usage_records_user_id", "resource_usage_records", ["user_id"])
    op.create_index("ix_resource_usage_account_status", "resource_usage_records", ["account_id", "status"])
    op.create_index("ix_resource_usage_resource", "resource_usage_records", ["resource_type", "resource_id"])

    op.create_table(
        "credit_price_rules",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_key", sa.String(128), nullable=False),
        sa.Column("unit", sa.String(32), nullable=False),
        sa.Column("credit_amount", sa.BigInteger(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("resource_type", "resource_key", "unit", name="uq_credit_price_rules_resource"),
    )

    op.create_table(
        "dataset_prices",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("dataset_id", sa.CHAR(36), nullable=False),
        sa.Column("credit_amount", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.Enum("active", "inactive", name="datasetpricestatus"), server_default="active", nullable=False),
        sa.Column("created_by_user_id", sa.CHAR(36), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dataset_id", name="uq_dataset_prices_dataset_id"),
    )
    op.create_index("ix_dataset_prices_status", "dataset_prices", ["status"])

    op.create_table(
        "dataset_purchase_grants",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("dataset_id", sa.CHAR(36), nullable=False),
        sa.Column("account_id", sa.CHAR(36), nullable=False),
        sa.Column("user_id", sa.CHAR(36), nullable=False),
        sa.Column("org_id", sa.CHAR(36), nullable=True),
        sa.Column("resource_usage_record_id", sa.CHAR(36), nullable=True),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("source_id", sa.String(128), nullable=False),
        sa.Column("status", sa.Enum("active", "refunded", name="datasetpurchasegrantstatus"), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["credit_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resource_usage_record_id"], ["resource_usage_records.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dataset_id", "account_id", name="uq_dataset_purchase_grants_dataset_account"),
    )
    op.create_index("ix_dataset_purchase_grants_user", "dataset_purchase_grants", ["user_id", "status"])
    op.create_index("ix_dataset_purchase_grants_org", "dataset_purchase_grants", ["org_id", "status"])

    op.create_table(
        "remote_training_jobs",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("account_id", sa.CHAR(36), nullable=False),
        sa.Column("usage_record_id", sa.CHAR(36), nullable=True),
        sa.Column("org_id", sa.CHAR(36), nullable=True),
        sa.Column("user_id", sa.CHAR(36), nullable=False),
        sa.Column("username", sa.String(128), nullable=False),
        sa.Column("task_name", sa.String(150), nullable=False),
        sa.Column("gpu_type", sa.String(128), nullable=False),
        sa.Column("gpu_count", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("expected_seconds", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("hold_credit", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("settled_credit", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.Enum("held", "running", "settled", "failed", name="remotetrainingjobstatus"), server_default="held", nullable=False),
        sa.Column("request_json", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["credit_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["usage_record_id"], ["resource_usage_records.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_remote_training_jobs_account_id", "remote_training_jobs", ["account_id"])
    op.create_index("ix_remote_training_jobs_org_id", "remote_training_jobs", ["org_id"])
    op.create_index("ix_remote_training_jobs_user_id", "remote_training_jobs", ["user_id"])
    op.create_index("ix_remote_training_jobs_account_status", "remote_training_jobs", ["account_id", "status"])
    op.create_index("ix_remote_training_jobs_user_task_status", "remote_training_jobs", ["user_id", "task_name", "status"])

    _seed_packages()
    _seed_training_rate()
    _backfill_personal_accounts()
    _backfill_contribution_grants()


def downgrade() -> None:
    op.drop_index("ix_remote_training_jobs_user_task_status", table_name="remote_training_jobs")
    op.drop_index("ix_remote_training_jobs_account_status", table_name="remote_training_jobs")
    op.drop_index("ix_remote_training_jobs_user_id", table_name="remote_training_jobs")
    op.drop_index("ix_remote_training_jobs_org_id", table_name="remote_training_jobs")
    op.drop_index("ix_remote_training_jobs_account_id", table_name="remote_training_jobs")
    op.drop_table("remote_training_jobs")

    op.drop_index("ix_dataset_purchase_grants_org", table_name="dataset_purchase_grants")
    op.drop_index("ix_dataset_purchase_grants_user", table_name="dataset_purchase_grants")
    op.drop_table("dataset_purchase_grants")

    op.drop_index("ix_dataset_prices_status", table_name="dataset_prices")
    op.drop_table("dataset_prices")
    op.drop_table("credit_price_rules")

    op.drop_index("ix_resource_usage_resource", table_name="resource_usage_records")
    op.drop_index("ix_resource_usage_account_status", table_name="resource_usage_records")
    op.drop_index("ix_resource_usage_records_user_id", table_name="resource_usage_records")
    op.drop_index("ix_resource_usage_records_org_id", table_name="resource_usage_records")
    op.drop_index("ix_resource_usage_records_account_id", table_name="resource_usage_records")
    op.drop_table("resource_usage_records")

    op.drop_index("ix_upload_reward_grants_account_status", table_name="upload_reward_grants")
    op.drop_index("ix_upload_reward_grants_account_id", table_name="upload_reward_grants")
    op.drop_table("upload_reward_grants")

    op.drop_index("ix_payment_orders_account_status", table_name="payment_orders")
    op.drop_index("ix_payment_orders_account_id", table_name="payment_orders")
    op.drop_table("payment_orders")

    op.drop_index("ix_recharge_packages_type_active", table_name="recharge_packages")
    op.drop_table("recharge_packages")

    op.drop_index("ix_credit_ledger_source", table_name="credit_ledger_entries")
    op.drop_index("ix_credit_ledger_account_created", table_name="credit_ledger_entries")
    op.drop_index("ix_credit_ledger_entries_account_id", table_name="credit_ledger_entries")
    op.drop_table("credit_ledger_entries")

    op.drop_index("ix_credit_accounts_org_user", table_name="credit_accounts")
    op.drop_index("ix_credit_accounts_user_id", table_name="credit_accounts")
    op.drop_index("ix_credit_accounts_org_id", table_name="credit_accounts")
    op.drop_table("credit_accounts")


def _seed_packages() -> None:
    values = []
    for account_type in ("data", "training"):
        for index, amount in enumerate((50, 100, 500, 1000)):
            values.append(
                f"(UUID(), '{account_type}', '{amount} credits', 'CNY', {amount * 100}, {amount}, 1, {index}, NOW(), NOW())"
            )
    op.execute(
        "INSERT INTO recharge_packages "
        "(id, account_type, name, fiat_currency, fiat_amount, credit_amount, is_active, sort_order, created_at, updated_at) "
        f"VALUES {', '.join(values)}"
    )


def _seed_training_rate() -> None:
    op.execute(
        "INSERT INTO credit_price_rules "
        "(id, resource_type, resource_key, unit, credit_amount, is_active, created_at, updated_at) "
        "VALUES (UUID(), 'remote_training', 'default', 'gpu_hour', 10, 1, NOW(), NOW())"
    )


def _backfill_personal_accounts() -> None:
    for account_type in ("data", "training"):
        op.execute(
            "INSERT INTO credit_accounts "
            "(id, org_id, user_id, account_type, org_scope_key, available_balance, held_balance, status, version, created_at, updated_at) "
            f"SELECT UUID(), NULL, users.id, '{account_type}', '__personal__', 100, 0, 'active', 0, NOW(), NOW() "
            "FROM users WHERE users.status = 'active'"
        )
        op.execute(
            "INSERT INTO credit_ledger_entries "
            "(id, account_id, entry_type, available_delta, held_delta, available_balance_after, held_balance_after, source_type, source_id, created_at) "
            f"SELECT UUID(), credit_accounts.id, 'initial_grant', 100, 0, 100, 0, 'system_initial_grant', "
            f"CONCAT('existing-', credit_accounts.user_id, '-{account_type}'), NOW() "
            "FROM credit_accounts "
            f"WHERE credit_accounts.account_type = '{account_type}' AND credit_accounts.org_scope_key = '__personal__'"
        )


def _backfill_contribution_grants() -> None:
    op.execute(
        "INSERT IGNORE INTO dataset_purchase_grants "
        "(id, dataset_id, account_id, user_id, org_id, resource_usage_record_id, source_type, source_id, status, created_at) "
        "SELECT UUID(), contributions.dataset_id, credit_accounts.id, contributions.user_id, NULL, NULL, "
        "'contribution', contributions.id, 'active', NOW() "
        "FROM contributions "
        "JOIN credit_accounts ON credit_accounts.user_id = contributions.user_id "
        "  AND credit_accounts.account_type = 'data' "
        "  AND credit_accounts.org_scope_key = '__personal__' "
        "WHERE contributions.status = 'passed' AND contributions.dataset_id IS NOT NULL"
    )
