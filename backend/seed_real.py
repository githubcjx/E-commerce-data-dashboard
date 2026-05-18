"""Import the user's real 数据源.xlsx into the acme tenant and report KPIs.

Flow:
  1. Login as platform admin (cjx) → create/ensure tenant "acme" + admin "acme_admin"
  2. Login as acme_admin → upload the real xlsx file
  3. Poll the import batch until done
  4. Query /api/dashboard/kpi and pretty-print the numbers
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import requests


API = "http://127.0.0.1:8000"

PLATFORM_USERNAME = "cjx"
PLATFORM_PASSWORD = "htcjx123."

TENANT_CODE = "acme"
TENANT_NAME = "Acme 电商科技"
TENANT_ADMIN_USERNAME = "acme_admin"
TENANT_ADMIN_PASSWORD = "acme1234"

DEFAULT_FILE = r"C:\Users\Admin\Pictures\数据源.xlsx"


def login(username: str, password: str) -> str:
    r = requests.post(f"{API}/api/auth/login", json={"username": username, "password": password}, timeout=10)
    r.raise_for_status()
    return r.json()["data"]["token"]


def fmt_currency(v: float) -> str:
    return f"¥{v:>14,.2f}"


def main(path: str) -> None:
    p = Path(path)
    if not p.exists():
        print(f"❌ File not found: {p}")
        sys.exit(1)

    print(f"[1/5] login as {PLATFORM_USERNAME}")
    token = login(PLATFORM_USERNAME, PLATFORM_PASSWORD)
    h_cjx = {"Authorization": f"Bearer {token}"}

    existing = requests.get(f"{API}/api/tenants", headers=h_cjx, timeout=10).json()["data"]
    tenant = next((t for t in existing if t["code"] == TENANT_CODE), None)
    if tenant:
        print(f"[2/5] tenant '{TENANT_CODE}' exists (id={tenant['id']})")
    else:
        print(f"[2/5] create tenant '{TENANT_CODE}' + admin '{TENANT_ADMIN_USERNAME}'")
        r = requests.post(f"{API}/api/tenants", headers=h_cjx, json={
            "code": TENANT_CODE, "name": TENANT_NAME,
            "admin_username": TENANT_ADMIN_USERNAME,
            "admin_password": TENANT_ADMIN_PASSWORD,
            "admin_display_name": "Acme 管理员",
        }, timeout=10)
        r.raise_for_status()
        tenant = r.json()["data"]

    print(f"[3/5] login as {TENANT_ADMIN_USERNAME}")
    token2 = login(TENANT_ADMIN_USERNAME, TENANT_ADMIN_PASSWORD)
    h = {"Authorization": f"Bearer {token2}"}

    print(f"[4/5] upload {p.name} ({p.stat().st_size:,} bytes)")
    with p.open("rb") as f:
        files = {"file": (p.name, f.read(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    r = requests.post(f"{API}/api/import/upload", headers=h, files=files, timeout=120)
    r.raise_for_status()
    batch_id = r.json()["data"]["id"]
    print(f"    batch_id = {batch_id}")

    print(f"[5/5] polling import status...")
    for i in range(180):
        time.sleep(1)
        b = requests.get(f"{API}/api/import/batches/{batch_id}", headers=h, timeout=10).json()["data"]
        if b["status"] != "processing":
            print(
                f"    done: status={b['status']} "
                f"inserted={b['inserted_rows']} updated={b['updated_rows']} "
                f"failed={b['failed_rows']} total={b['total_rows']}"
            )
            if b.get("error_message"):
                print(f"    error: {b['error_message']}")
            break
        if i % 5 == 0:
            print(f"    ...{i}s elapsed")
    else:
        print("    timeout")
        return

    # Pull KPI for a date in the file
    print()
    print("─" * 70)
    for end_date in ("2026-05-10", "2026-05-05", "2026-05-01"):
        kpi = requests.get(
            f"{API}/api/dashboard/kpi",
            headers=h,
            params={"end_date": end_date, "granularity": "day"},
            timeout=20,
        ).json()["data"]
        print(f"\nKPI · {end_date} (day):")
        for it in kpi["items"]:
            val_str = (
                fmt_currency(it["value"]) if it["format"] == "currency"
                else f"{it['value']:>15,.2f}%" if it["format"] == "percent"
                else f"{int(it['value']):>15,}"
            )
            prev_str = (
                fmt_currency(it["prev"]) if it["format"] == "currency"
                else f"{it['prev']:.2f}%" if it["format"] == "percent"
                else f"{int(it['prev']):,}"
            )
            delta = f"{it['delta_pct']:+.2f}%" if it["delta_pct"] is not None else "—"
            print(f"  {it['label']:<14} {val_str}   上期 {prev_str:<12}   Δ {delta}")

    print()
    print("─" * 70)
    cat = requests.get(
        f"{API}/api/dashboard/category",
        headers=h,
        params={"end_date": "2026-05-10", "granularity": "day"},
        timeout=20,
    ).json()["data"]
    print("\n类目分类汇总 · 2026-05-10 (day):")
    print(f"  {'类目':<12} {'销售额':>14} {'利润':>14} {'毛利率':>10} {'退款率':>10}")
    for c in cat:
        print(f"  {c['name']:<12} {c['sales']:>14,.2f} {c['profit']:>14,.2f} {c['gross_margin']:>9.2f}% {c['refund_rate']:>9.2f}%")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_FILE)
