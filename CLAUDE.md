# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

电商数据看板系统 — a multi-tenant e-commerce sales dashboard. Excel import → PostgreSQL → KPI / trend / category analytics with drag-reorderable panels. Vue 3 SPA + FastAPI (async) backend.

> The root `README.md` predates the multi-tenant rebuild and is partly stale (it describes a single team-password login and a flat shop list). Trust the code and this file over the README for auth, roles, fee config, and the dev server port.

## Commands

There is **no `venv`** — backend runs on the global Python (`python` / `Python310`). Run everything below from the directory shown.

```powershell
# Backend (cwd = backend/)
pip install -r requirements.txt
uvicorn app.main:app --reload          # serves :8000; auto-creates tables + bootstraps platform admin on startup
python -m pytest                       # full suite (test_apportionment.py + test_targets.py)
python -m pytest tests/test_apportionment.py::test_canonical_user_example -v   # single test
python -c "import py_compile; py_compile.compile(r'app\services\dashboard_service.py', doraise=True)"  # quick syntax check

# Frontend (cwd = frontend/)
npm install
npm run dev                            # Vite on :9586, proxies /api → :8000
npm run build                          # → dist/ (also emits dist/version.json for the update-banner poll)

# Full stack via Docker — LOCAL ONLY (db + backend + frontend, no caddy; frontend on 127.0.0.1:8080)
docker compose up -d --build
```

### Deployment (production)

**Always give the user the full production command — never the bare `docker compose up -d --build`.** Prod stacks the base compose file with `deploy/docker-compose.prod.yml`, which adds the **caddy** container (public reverse proxy + auto-HTTPS). Omitting `-f deploy/docker-compose.prod.yml` drops caddy and the site becomes unreachable from the internet. The server lives at `/opt/ec-dashboard`.

```bash
cd /opt/ec-dashboard
sudo git pull
sudo docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml up -d --build
```

The trailing `up -d --build` (no service name) rebuilds everything; unchanged containers (db, caddy) are left as-is. You *can* limit the rebuild to one service (`... up -d --build frontend`), but only when you're certain the change touched just that side — a frontend-only rebuild against an unchanged backend will break if the API contract changed. When unsure, rebuild everything. A change that touches both `backend/` and `frontend/` (e.g. adding an API field the UI reads) **must** rebuild both.

Two test styles: `test_apportionment.py` is **pure-function** (dict-shaped inputs, no DB) — `conftest.py` points `DATABASE_URL` at in-memory SQLite just so the import chain (`app.db`) loads. `test_targets.py` is **SQLite-backed**: each test spins up its OWN in-memory async engine (`create_async_engine(... StaticPool)`) + `create_all`, seeds rows, and drives the async service/endpoints via `asyncio.run` (the suite has no `pytest-asyncio` dep). That's the right pattern for DB-backed logic — just don't add fixtures expecting a real Postgres.

### Migrations

Schema changes are hand-written **idempotent scripts** in `backend/scripts/migrate_*.py`, not Alembic. Each detects dialect (postgresql/sqlite), checks if the change is already applied, and is safe to re-run. SQLAlchemy `create_all` on startup only creates *missing* tables — it never alters existing ones, so column adds/drops MUST go through a migrate script. Run after pulling:

```bash
docker compose exec backend python -m scripts.migrate_fee_group_monthly_cost
```

Operational scripts (all support `--tenant <code>`, most have a dry-run default and require `--apply`/`--yes` to mutate): `audit_profit` (reproduce dashboard 利润额 from raw SUM), `cleanup_rolledback` (orphaned rows after rollback), `purge_tenant_data` (wipe sales+batches, keep config).

## Architecture

### Two-database support (Postgres prod, SQLite dev/test)

`config.py` defaults `database_url` to `sqlite+aiosqlite:///./demo.db` so the app runs with zero infra; prod overrides to `postgresql+asyncpg://...`. This dual-target constraint shapes the code:
- `db.py` applies SQLite-only PRAGMAs (WAL, busy_timeout) so background imports don't lock out auth reads.
- `models.py` uses `BigInteger().with_variant(Integer, "sqlite")` for autoincrement PKs and **`JSON` not `JSONB`** (`data_scope_owners`) so the same column works on both.
- `import_service.py` picks the dialect-specific `insert` for UPSERT at import time.
- Migration scripts branch on `engine.dialect.name`.

### Multi-tenancy + 4-role hierarchy (the core access model)

Every business row carries `tenant_id`. Roles (see `models.py` top + `security.py`):
- **platform_admin** (`cjx`, `tenant_id=NULL`) — manages all tenants. Has no own data; impersonates a tenant via the `X-Tenant-Id` header (`effective_tenant_id`).
- **tenant_super_admin** — full power within tenant: create users, set roles, set data scopes.
- **tenant_admin** — backend access but only *edits* existing 普通用户 (name/password); can manage data scopes only if `can_manage_scope` is set.
- **tenant_user** — dashboard only; sees rows limited by `data_scope_owners`.

`data_scope_owners` is the row-level filter, and its three states are load-bearing — preserve this exactly: **`NULL` = unrestricted**, **`[]` = sees nothing**, **`[...]` = `WHERE owner IN (...)`**. Admin tiers + platform_admin always behave as NULL regardless of stored value. Resolved by `effective_scope_owners(user)` and threaded into every dashboard query as `scope_owners`. Auth guards (`require_backend_access`, `require_tenant_super_admin`, `require_import_access`, `require_platform_admin`) gate routers; the frontend router (`createWebHashHistory`) mirrors the same role sets for UX but is **not** the security boundary — the backend guards are.

### Request flow

Frontend `api/client.js` (axios) attaches the Bearer token, unwraps the `{code, data, msg}` envelope (rejecting on `code !== 0`), and on 401 clears the session and redirects to `#/login`. All API responses use `ApiResponse` (`schemas.py`). Dashboard endpoints take `_common` query params where multi-selects are comma-joined strings and `"all"`/empty → `None` (no filter).

### 公司利润率 fixed-cost apportionment — the trickiest logic

Lives in `dashboard_service.py` (`_compute_fixed_cost_deductions`, `_load_dept_day_group_sales`, `_dept_day_group_sales`) and is covered by `tests/test_apportionment.py`. The model is **per-day apportionment with a whole-department denominator**:

```
daily_cost(group) = monthly_amount / days_in_that_month       # from fee_group_monthly_cost
dept_day(group)   = WHOLE department's sales for that group on that day   # the DENOMINATOR
shop_deduction   += daily_cost × (shop_sales_on_day / dept_day(group))
公司利润率        = SUM(profit_s − fixed_cost_s − sales_s × tax_rate_s) / SUM(sales_s)
```

**Critical invariant:** the denominator is the whole department, NOT the filtered subset. The denominator query (`_load_dept_day_group_sales`) deliberately **drops** the owner/category/shop-picker filters but **keeps** `scope_owners` (data isolation must never be bypassed). If the denominator ever shrinks with the filter, filtering to one owner/shop dumps the *entire* department burden onto them — the exact bug this design fixed. Rules: a (group, day) with 0 department sales isn't deducted; days after `today` are skipped (已发生天数 only). Because every granularity (KPI, trend bucket, category row) is a plain sum of the same per-day atoms, they reconcile exactly.

Fee config is **per-shop** on the `shops` table (`fee_group_name` is a free-text label, `ship_service_tax_rate` is the %-fee), NOT linked to the `departments` table. `fee_group_name` keys into `fee_group_monthly_cost` (per tenant, per group, per `YYYY-MM`). The `departments` table is used only for the 部门视角 picker via `Shop.view_department_id`.

### Import pipeline

`import_api` (route, `require_import_access`) spools the upload to disk then runs `import_service.run_import` as a background task. `excel_parser.parse_workbook` streams rows with openpyxl `read_only=True` (10万-row files don't blow memory) and cleans percentages (`8.97%` → `0.0897`). UPSERT key is `(tenant_id, shop_code, date, sku)`. Two import subtleties to respect:
- **In-buffer dedup** (`seen_keys`): the same business key appearing twice in one batch is collapsed to last-write-wins, else Postgres errors `ON CONFLICT DO UPDATE cannot affect row a second time`.
- **batch_id on conflict**: an UPSERT updating an existing row rewrites its `batch_id` to the new batch — so rolling back the *old* batch can leave orphans (hence `cleanup_rolledback`).

Shops are auto-created/synced from imports — admins never type a new shop, they only configure fee fields on shops that imports surfaced.

### Frontend layout state

`stores/dashboard.js` holds the 8 KPI metric order + section order; layout persists per-(tenant, user) via `dashboard_layouts` (`PUT/GET /api/layout`). On first open the dashboard anchors its default date window to the latest imported-data date (not literal today) so users don't land on an empty window. Build version = `Date.now()` baked into the bundle + `version.json`; `stores/version.js` polls it to show a refresh banner after a deploy.

## Conventions

- Line endings: shell/yaml/Dockerfile/conf are forced to **LF** via `.gitattributes` (they run on Linux). Python files are CRLF in the working tree on Windows — that's expected; don't "fix" it.
- Rates/percentages are stored as decimals (0.0897), formatted for display on the frontend.
- Rate-type KPIs are computed as ratio-of-totals (`SUM(num)/SUM(den)`), never an average of per-row rates, to avoid Simpson's paradox.
- Commit messages in this repo are written in Chinese with a concise summary line + bullet rationale.
