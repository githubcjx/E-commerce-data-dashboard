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


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    tenant_id: int | None = None
    display_name: str | None = None
    department_id: int | None = None
    department_name: str | None = None
    # Per-user department fixed_profit_rate (denormalized into the user row
    # for the dashboard to read on its own login — avoids an extra round trip).
    # NULL for super_admin / platform_admin (no department).
    department_fixed_profit_rate: float | None = None
    # NULL means "unrestricted" (super_admin & platform_admin behave that way
    # regardless of stored value). An empty list means "scoped to nothing".
    data_scope_owners: list[str] | None = None
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
    # Department to drop the new user into. Required for non-super roles
    # (validated at the API layer to keep the error message friendly).
    department_id: int | None = None
    # NULL = unrestricted (default). List of owner names = scoped view.
    data_scope_owners: list[str] | None = None
    # Only honored when actor is platform_admin (used from /admin/users?tenant_id=).
    tenant_id: int | None = None


class UserUpdate(BaseModel):
    password: str | None = Field(default=None, min_length=6, max_length=128)
    role: str | None = None
    display_name: str | None = Field(default=None, max_length=64)
    # Transfer a user to a different department. Omit to leave unchanged.
    department_id: int | None = None
    # Sent as a list to set scope, or as null to clear (= unrestricted).
    # Omit the key entirely to leave scope unchanged.
    data_scope_owners: list[str] | None = None


# ---------- Departments ----------

class DepartmentMember(BaseModel):
    id: int
    username: str
    display_name: str | None = None
    role: str

    class Config:
        from_attributes = True


class DepartmentOut(BaseModel):
    id: int
    tenant_id: int
    name: str
    fixed_profit_rate: float
    member_count: int = 0
    created_at: datetime

    class Config:
        from_attributes = True


class DepartmentDetailOut(DepartmentOut):
    members: list[DepartmentMember] = []


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    fixed_profit_rate: float = Field(..., ge=0, lt=1)
    member_ids: list[int] = Field(default_factory=list)
    # Honored only when actor is platform_admin (multi-tenant management).
    tenant_id: int | None = None


class DepartmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    fixed_profit_rate: float | None = Field(default=None, ge=0, lt=1)
    # If present, replaces the member list wholesale (members not in the new
    # list are unassigned; members newly in the list are assigned).
    member_ids: list[int] | None = None


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
