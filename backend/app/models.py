from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text,
    UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


# Role values — three-level hierarchy.
ROLE_PLATFORM_ADMIN = "platform_admin"
ROLE_TENANT_ADMIN = "tenant_admin"
ROLE_TENANT_USER = "tenant_user"

TENANT_STATUS_ACTIVE = "active"
TENANT_STATUS_DISABLED = "disabled"


class Tenant(Base):
    """A customer company. Every business row is scoped by tenant_id."""
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=TENANT_STATUS_ACTIVE)
    created_by: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # NULL for platform_admin (cjx) — they don't belong to any tenant.
    tenant_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )

    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default=ROLE_TENANT_USER)
    display_name: Mapped[str | None] = mapped_column(String(64))
    created_by: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class SalesRecord(Base):
    __tablename__ = "sales_records"
    __table_args__ = (
        # Business key is per-tenant so two companies can have the same SKU on
        # the same day without collision.
        UniqueConstraint("tenant_id", "shop_code", "date", "sku", name="uq_tenant_shop_date_sku"),
        Index("ix_sales_tenant_date", "tenant_id", "date"),
        Index("ix_sales_tenant_date_shop", "tenant_id", "date", "shop_code"),
        Index("ix_sales_tenant_date_cat", "tenant_id", "date", "category"),
        Index("ix_sales_tenant_date_owner", "tenant_id", "date", "owner"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )

    tenant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )

    shop_name: Mapped[str | None] = mapped_column(String(200))
    shop_code: Mapped[str] = mapped_column(String(64), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    sku: Mapped[str] = mapped_column(String(300), nullable=False)
    category: Mapped[str | None] = mapped_column(String(100))
    # Excel field "负责人" — distinct from the system user who imported the row.
    owner: Mapped[str | None] = mapped_column(String(100))

    order_qty: Mapped[int] = mapped_column(Integer, default=0)

    pre_ship_refund_rate: Mapped[Decimal] = mapped_column(Numeric(20, 6), default=0)
    post_ship_refund_amt: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    post_ship_platform_subsidy: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    post_ship_refund_rate: Mapped[Decimal] = mapped_column(Numeric(20, 6), default=0)

    actual_income: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    refund_total: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    refund_rate: Mapped[Decimal] = mapped_column(Numeric(20, 6), default=0)
    income_total: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)

    material_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    material_cost_rate: Mapped[Decimal] = mapped_column(Numeric(20, 6), default=0)
    cost_total: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)

    gift_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    gift_cost_rate: Mapped[Decimal] = mapped_column(Numeric(20, 6), default=0)
    gross_margin: Mapped[Decimal] = mapped_column(Numeric(20, 6), default=0)
    marketing_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    marketing_cost_rate: Mapped[Decimal] = mapped_column(Numeric(20, 6), default=0)
    shipping_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    shipping_cost_rate: Mapped[Decimal] = mapped_column(Numeric(20, 6), default=0)
    platform_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    platform_cost_rate: Mapped[Decimal] = mapped_column(Numeric(20, 6), default=0)

    profit: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    profit_rate: Mapped[Decimal] = mapped_column(Numeric(20, 6), default=0)

    batch_id: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ImportBatch(Base):
    __tablename__ = "import_batches"
    __table_args__ = (Index("ix_batch_tenant_created", "tenant_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # NULL after the importing user is deleted — keeps the batch audit trail.
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, default=0)
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    inserted_rows: Mapped[int] = mapped_column(Integer, default=0)
    updated_rows: Mapped[int] = mapped_column(Integer, default=0)
    failed_rows: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="processing")
    error_message: Mapped[str | None] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DashboardLayout(Base):
    __tablename__ = "dashboard_layouts"

    # Per-user layout, partitioned by tenant.
    tenant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    layout_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
