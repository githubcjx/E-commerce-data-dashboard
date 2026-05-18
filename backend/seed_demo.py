"""Bootstrap a demo tenant ("acme") and seed it with 30 days of sales data.

Flow:
  1. login as platform admin (cjx)
  2. POST /api/tenants → atomically create tenant "acme" + first admin "acme_admin"
  3. login as acme_admin
  4. POST /api/import/upload with a generated xlsx → imports into acme's tenant

Run from the project root:
    python backend/seed_demo.py
"""
from __future__ import annotations

import io
import random
import time
from datetime import date, timedelta

import requests
from openpyxl import Workbook


API = "http://127.0.0.1:8000"

PLATFORM_USERNAME = "cjx"
PLATFORM_PASSWORD = "htcjx123."

TENANT_CODE = "acme"
TENANT_NAME = "Acme 电商科技"
TENANT_ADMIN_USERNAME = "acme_admin"
TENANT_ADMIN_PASSWORD = "acme1234"

SHOPS = [
    ("旗舰店·天猫", "S001"),
    ("旗舰店·京东", "S002"),
    ("专营店·抖音", "S003"),
    ("海外仓·速卖通", "S004"),
]
OWNERS = ["陈雨晴", "周明", "林婉", "Daniel Park"]
CATEGORIES = ["家居家纺", "美妆个护", "服饰鞋包", "数码配件", "母婴玩具"]

HEADER = [
    "店铺", "店铺编码", "日期", "分类", "类目分类", "负责人",
    "资料-实发数量(订单)",
    "售后-发货前退款占比", "售后-发货后实退金额", "售后-发货后退平台补贴", "售后-发货后退款占比",
    "收入-实收金额", "收入-退款金额合计", "收入-退款占比", "收入-收入总额",
    "成本-耗材成本", "成本-耗材成本占比", "成本-成本总额",
    "费用-赠品成本", "费用-赠品成本占比", "费用-毛利率1",
    "费用-营销费用", "费用-营销费用占比", "费用-快递费用", "费用-快递费用占比",
    "费用-平台费用", "费用-平台费用占比",
    "利润-经营利润", "利润-经营利润率",
]


def build_xlsx() -> bytes:
    random.seed(42)
    wb = Workbook(write_only=True)
    ws = wb.create_sheet("店铺数据")
    ws.append(HEADER)

    end_date = date(2026, 5, 10)
    for offset in range(30):
        d = end_date - timedelta(days=29 - offset)
        for (shop_name, shop_code) in SHOPS:
            owner = random.choice(OWNERS)
            for cat in CATEGORIES:
                sku = f"{cat}-{shop_code}-{random.randint(1, 3):02d}"
                qty = random.randint(20, 220)
                income = round(qty * random.uniform(38, 180), 2)
                refund = round(income * random.uniform(0.05, 0.32), 2)
                income_total = round(income + refund, 2)
                cost = round(income * random.uniform(0.42, 0.72), 2)
                gift = round(income * random.uniform(0.01, 0.04), 2)
                shipping = round(income * random.uniform(0.07, 0.14), 2)
                marketing = round(income * random.uniform(0.18, 0.55), 2)
                platform = round(income * random.uniform(0.04, 0.09), 2)
                profit = round(income - cost - gift - shipping - marketing - platform, 2)
                ws.append([
                    shop_name, shop_code, d.isoformat(), sku, cat, owner,
                    qty,
                    f"{random.uniform(2, 8):.2f}%", round(refund * 0.6, 2), round(refund * 0.05, 2),
                    f"{(refund / max(income_total, 1)) * 100:.2f}%",
                    income, refund, f"{(refund / max(income_total, 1)) * 100:.2f}%", income_total,
                    cost, f"{(cost / max(income, 1)) * 100:.2f}%", round(cost + gift, 2),
                    gift, f"{(gift / max(income, 1)) * 100:.2f}%",
                    f"{((income - cost) / max(income, 1)) * 100:.2f}%",
                    marketing, f"{(marketing / max(income, 1)) * 100:.2f}%",
                    shipping, f"{(shipping / max(income, 1)) * 100:.2f}%",
                    platform, f"{(platform / max(income, 1)) * 100:.2f}%",
                    profit, f"{(profit / max(income, 1)) * 100:.2f}%",
                ])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def login(username: str, password: str) -> str:
    r = requests.post(f"{API}/api/auth/login", json={"username": username, "password": password}, timeout=10)
    r.raise_for_status()
    return r.json()["data"]["token"]


def main() -> None:
    print(f"[1/4] login as platform admin {PLATFORM_USERNAME}")
    token = login(PLATFORM_USERNAME, PLATFORM_PASSWORD)
    h_cjx = {"Authorization": f"Bearer {token}"}

    # idempotent: skip create if tenant exists
    existing = requests.get(f"{API}/api/tenants", headers=h_cjx, timeout=10).json()["data"]
    tenant = next((t for t in existing if t["code"] == TENANT_CODE), None)
    if tenant:
        print(f"[2/4] tenant '{TENANT_CODE}' already exists (id={tenant['id']}), skipping create")
    else:
        print(f"[2/4] create tenant '{TENANT_CODE}' + first admin '{TENANT_ADMIN_USERNAME}'")
        r = requests.post(f"{API}/api/tenants", headers=h_cjx, json={
            "code": TENANT_CODE,
            "name": TENANT_NAME,
            "admin_username": TENANT_ADMIN_USERNAME,
            "admin_password": TENANT_ADMIN_PASSWORD,
            "admin_display_name": "Acme 管理员",
        }, timeout=10)
        r.raise_for_status()
        tenant = r.json()["data"]
        print(f"    tenant_id={tenant['id']}")

    print(f"[3/4] login as tenant admin {TENANT_ADMIN_USERNAME}")
    token2 = login(TENANT_ADMIN_USERNAME, TENANT_ADMIN_PASSWORD)
    h_acme = {"Authorization": f"Bearer {token2}"}

    print("[4/4] generate + upload 30-day demo workbook")
    blob = build_xlsx()
    files = {"file": ("demo_30d.xlsx", blob, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    r = requests.post(f"{API}/api/import/upload", headers=h_acme, files=files, timeout=60)
    r.raise_for_status()
    batch_id = r.json()["data"]["id"]
    print(f"    batch_id = {batch_id}")

    for _ in range(30):
        time.sleep(1)
        b = requests.get(f"{API}/api/import/batches/{batch_id}", headers=h_acme, timeout=10).json()["data"]
        if b["status"] != "processing":
            print(
                f"    done: status={b['status']} "
                f"inserted={b['inserted_rows']} updated={b['updated_rows']} "
                f"failed={b['failed_rows']} total={b['total_rows']}"
            )
            if b.get("error_message"):
                print(f"    error: {b['error_message']}")
            print()
            print("✅ Demo ready. Login on http://localhost:5173 as:")
            print(f"   - {PLATFORM_USERNAME} / {PLATFORM_PASSWORD}   (platform admin — manage tenants)")
            print(f"   - {TENANT_ADMIN_USERNAME} / {TENANT_ADMIN_PASSWORD}   (Acme tenant admin — see Acme dashboard)")
            return
    print("    timeout waiting for import to finish")


if __name__ == "__main__":
    main()
