from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, ForeignKey, Index, Integer, JSON, Numeric,
    String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


# Role values — four-level hierarchy.
#   platform_admin     : cjx, no tenant. Manages all tenants/users.
#   tenant_super_admin : initial account created with the tenant. Full
#                        privileges within the tenant — can create users,
#                        set roles (admin/user), set per-user data scopes.
#   tenant_admin       : has backend access, but only to EDIT existing
#                        普通用户 (display name / password). Cannot create
#                        or delete accounts, cannot change roles or scopes.
#   tenant_user        : regular user. Sees only data within their assigned
#                        owner list (data_scope_owners), or all if NULL.
ROLE_PLATFORM_ADMIN = "platform_admin"
ROLE_TENANT_SUPER_ADMIN = "tenant_super_admin"
ROLE_TENANT_ADMIN = "tenant_admin"
ROLE_TENANT_USER = "tenant_user"

# Roles that have access to the /admin backend page.
BACKEND_ROLES = {ROLE_PLATFORM_ADMIN, ROLE_TENANT_SUPER_ADMIN, ROLE_TENANT_ADMIN}

TENANT_STATUS_ACTIVE = "active"
TENANT_STATUS_DISABLED = "disabled"

# Default "company fixed profit rate" — subtracted from 经营利润率 to derive
# 公司利润率. Stored per-tenant so each company can tune their own number.
DEFAULT_FIXED_PROFIT_RATE = Decimal("0.13")


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


class Department(Base):
    """A team / 部门 inside a tenant.

    Departments here are used purely for organisation + 部门视角:
      - Members come from the user_departments M2M table (a user can
        belong to multiple departments).
      - Shops can be assigned to a department's 视角 via
        Shop.view_department_id — the dashboard's 部门视角 picker uses
        this to limit which shops' data shows up.

    NOTE: the fee config (人员均摊, 发货客服税费, 费用所属部门名称) lives
    PER-SHOP on the shops table — and the "费用所属部门名称" there is a
    free-text label, NOT linked to this departments table in any way.
    """
    __tablename__ = "departments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_dept_tenant_name"),
        Index("ix_dept_tenant", "tenant_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_by: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class UserDepartment(Base):
    """M2M between users and departments — a user can belong to many.

    We keep this as an explicit model (rather than a Table()) so it can
    show up in SQLAlchemy's metadata + future timestamp columns can be
    added without a major migration.
    """
    __tablename__ = "user_departments"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    department_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("departments.id", ondelete="CASCADE"), primary_key=True
    )


class Shop(Base):
    """A storefront inside a tenant.

    Shops are auto-created from sales_record imports — admins never type
    in a new shop. They configure per-shop:
      - view_department_id: which department's 部门视角 reveals this shop
        (this IS an FK to departments — used by the 部门视角 filter)
      - fee_group_name: a FREE-TEXT label, purely cosmetic, used to group
        shops with the same fee config in the 店铺管理 UI. It has NO
        relation to the departments table.
      - per_capita_share, ship_service_tax_rate: the two fee values that
        feed the 公司利润率 formula

    Formula (per-shop, then aggregated across selected shops):
        adj_profit_s  = profit_s − per_capita_share_s − sales_s × tax_rate_s
        公司利润率   = SUM(adj_profit_s) / SUM(sales_s)
    """
    __tablename__ = "shops"
    __table_args__ = (
        UniqueConstraint("tenant_id", "shop_code", name="uq_shop_tenant_code"),
        Index("ix_shop_tenant", "tenant_id"),
        Index("ix_shop_view_dept", "view_department_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    shop_code: Mapped[str] = mapped_column(String(64), nullable=False)
    shop_name: Mapped[str | None] = mapped_column(String(200))
    view_department_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("departments.id", ondelete="SET NULL")
    )
    fee_group_name: Mapped[str | None] = mapped_column(String(100))
    per_capita_share: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, default=Decimal("0"), server_default="0",
    )
    ship_service_tax_rate: Mapped[Decimal] = mapped_column(
        Numeric(6, 4), nullable=False, default=Decimal("0"), server_default="0",
    )
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
    # Department membership lives in user_departments (M2M). The old
    # single-valued users.department_id column is dropped by the migration.
    # Per-user data scope. Set by super_admin (or by a tenant_admin whose
    # can_manage_scope flag is true) via the admin panel.
    #   NULL  → unrestricted (default; admin tiers and platform_admin always
    #           behave as if NULL regardless of stored value).
    #   []    → user sees no rows (deliberately scoped to nothing).
    #   [...] → WHERE sales_records.owner IN (this list).
    # JSON, not JSONB, because we need the same type to work under SQLite too.
    data_scope_owners: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    # Tenant_admin permission switch: when true, this admin may edit the
    # data_scope_owners of 普通用户 in their tenant. Toggled by the
    # tenant_super_admin. Always false for tenant_user, ignored for
    # super_admin / platform_admin (they have full power anyway).
    can_manage_scope: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0",
    )
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
