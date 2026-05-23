from datetime import date, datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    code: int = 0
    data: T | None = None
    msg: str = "ok"


# ---------- Auth ----------

class LoginRequest(BaseModel):
    username: str
    password: str


class TenantBrief(BaseModel):
    id: int
    code: str
    name: str
    status: str

    class Config:
        from_attributes = True


class DepartmentBrief(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    tenant_id: int | None = None
    display_name: str | None = None
    # Users now belong to MANY departments (M2M). Empty list for super-admins
    # and for users who haven't been assigned yet.
    departments: list[DepartmentBrief] = []
    # NULL means "unrestricted" (admin tiers + platform_admin behave that way
    # regardless of stored value). An empty list means "scoped to nothing".
    data_scope_owners: list[str] | None = None
    # Tenant_admin scope-management switch (see model). For tenant_user it
    # is always false. Surfaced so the frontend can hide the data-scope
    # editor UI when an admin doesn't have the right.
    can_manage_scope: bool = False
    created_at: datetime

    class Config:
        from_attributes = True


class LoginResponse(BaseModel):
    token: str
    expire_at: datetime
    user: UserOut
    tenant: TenantBrief | None = None


# ---------- Tenants ----------

class TenantCreate(BaseModel):
    code: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=200)
    admin_username: str = Field(min_length=2, max_length=64)
    admin_password: str = Field(min_length=6, max_length=128)
    admin_display_name: str | None = Field(default=None, max_length=64)


class TenantUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    status: str | None = None  # "active" | "disabled"


class TenantOut(BaseModel):
    id: int
    code: str
    name: str
    status: str
    created_at: datetime
    user_count: int = 0

    class Config:
        from_attributes = True


# ---------- Users ----------

class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    # Allowed values: "tenant_admin" | "tenant_user". The super_admin role
    # is *not* assignable here — it's reserved for the initial tenant account.
    role: str = Field(default="tenant_user")
    display_name: str | None = Field(default=None, max_length=64)
    # Departments the new user belongs to (M2M). Required (non-empty) for
    # non-super roles; validated at the API layer.
    department_ids: list[int] = Field(default_factory=list)
    # NULL = unrestricted (default). List of owner names = scoped view.
    data_scope_owners: list[str] | None = None
    # Only meaningful when role=tenant_admin. False by default. Setter
    # restricted to super at the API layer.
    can_manage_scope: bool = False
    # Only honored when actor is platform_admin (used from /admin/users?tenant_id=).
    tenant_id: int | None = None


class UserUpdate(BaseModel):
    password: str | None = Field(default=None, min_length=6, max_length=128)
    role: str | None = None
    display_name: str | None = Field(default=None, max_length=64)
    # Replace the user's department set wholesale. Omit to leave unchanged.
    department_ids: list[int] | None = None
    # Sent as a list to set scope, or as null to clear (= unrestricted).
    # Omit the key entirely to leave scope unchanged.
    data_scope_owners: list[str] | None = None
    # Super-only field — toggled to grant/revoke an admin's right to
    # edit other users' data_scope_owners. Omit to leave unchanged.
    can_manage_scope: bool | None = None


# ---------- Departments ----------

class DepartmentMember(BaseModel):
    id: int
    username: str
    display_name: str | None = None
    role: str

    class Config:
        from_attributes = True


class DepartmentShop(BaseModel):
    """Shop summary for the department list — just enough to render the
    chip column "店铺 +N" in the admin view."""
    shop_code: str
    shop_name: str | None = None


class DepartmentOut(BaseModel):
    id: int
    tenant_id: int
    name: str
    # Full member / view-shop lists are surfaced inline so the list view can
    # show "前 3 + N" without an extra round-trip. The frontend slices
    # locally — these are bounded by the tenant size (typically < 100).
    members: list[DepartmentMember] = []
    view_shops: list[DepartmentShop] = []
    created_at: datetime

    class Config:
        from_attributes = True


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    member_ids: list[int] = Field(default_factory=list)
    # Shops shown under this department's 部门视角 on the dashboard. A shop
    # belongs to AT MOST ONE view-department — moving it here removes it
    # from any other department's view list.
    view_shop_codes: list[str] = Field(default_factory=list)
    # Honored only when actor is platform_admin (multi-tenant management).
    tenant_id: int | None = None


class DepartmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    # If present, replaces the member list wholesale (members not in the new
    # list are unassigned; members newly in the list are assigned).
    member_ids: list[int] | None = None
    # If present, replaces the view-shop list wholesale.
    view_shop_codes: list[str] | None = None


# ---------- Shops ----------

class ShopOut(BaseModel):
    id: int
    tenant_id: int
    shop_code: str
    shop_name: str | None = None
    view_department_id: int | None = None
    view_department_name: str | None = None
    # Free-text fee-group label — purely cosmetic, no FK relation.
    fee_group_name: str | None = None
    per_capita_share: float = 0.0
    ship_service_tax_rate: float = 0.0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ShopUpdate(BaseModel):
    """PATCH /api/shops/{shop_code} — only updates non-None fields."""
    view_department_id: int | None = None
    fee_group_name: str | None = Field(default=None, max_length=100)
    per_capita_share: float | None = Field(default=None, ge=0)
    ship_service_tax_rate: float | None = Field(default=None, ge=0, lt=1)


class ShopFeeGroupShop(BaseModel):
    """Single shop summary inside a fee-group row (for the list / edit form)."""
    shop_code: str
    shop_name: str | None = None


class ShopFeeGroupOut(BaseModel):
    """Aggregated 费用配置 — one row per distinct fee_group_name.

    Every shop tagged with the same fee_group_name shares the same values
    (per_capita_share / ship_service_tax_rate); the save endpoint
    enforces that on write. created_at / updated_at are min/max across
    the member shops so the list shows when the group first appeared
    and was last touched.
    """
    name: str
    per_capita_share: float = 0.0
    ship_service_tax_rate: float = 0.0
    shops: list[ShopFeeGroupShop] = []
    created_at: datetime
    updated_at: datetime


class ShopFeeGroupSave(BaseModel):
    """Create-or-update a fee group.

    original_name lets the edit dialog rename a group AND remove shops
    that the user un-ticked: any shop currently tagged with
    original_name but missing from shop_codes has its fee config
    cleared. Omit original_name to create a fresh group.
    """
    original_name: str | None = Field(default=None, max_length=100)
    name: str = Field(..., min_length=1, max_length=100)
    per_capita_share: float = Field(..., ge=0)
    ship_service_tax_rate: float = Field(..., ge=0, lt=1)
    shop_codes: list[str] = Field(default_factory=list)


# ---------- Import ----------

class ImportBatchOut(BaseModel):
    id: str
    filename: str
    file_size: int
    total_rows: int
    inserted_rows: int
    updated_rows: int
    failed_rows: int
    status: str
    error_message: str | None = None
    user_id: int | None = None
    created_at: datetime
    finished_at: datetime | None = None

    class Config:
        from_attributes = True


# ---------- Dashboard ----------

class KpiItem(BaseModel):
    key: str
    label: str
    value: float
    prev: float
    delta_pct: float | None
    higher_is_better: bool
    format: str
    series: list[float]


class LayoutPayload(BaseModel):
    layout_json: str
