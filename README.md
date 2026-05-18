# 电商数据看板系统

按照《电商数据看板系统-需求与技术方案》文档实现的全栈系统：

- **前端**：Vue 3 + Vite + Pinia + Vue Router + ECharts + xlsx（客户端预览）
- **后端**：FastAPI + SQLAlchemy 2 (async) + asyncpg + openpyxl（流式解析）
- **数据库**：PostgreSQL 15（UNIQUE + ON CONFLICT UPSERT）
- **部署**：Docker Compose 一键启动

UI 采用设计稿 `design/untitled/project/` 中的「sophisticated minimalism」风格（米白底 + 靛蓝主色 + 等宽数字），所有 CSS 设计 token 已迁移至 `frontend/src/styles/`。

## 快速启动（本地开发）

```bash
cp .env.example .env
# 编辑 .env 改 PLATFORM_ADMIN_PASSWORD 与 JWT_SECRET
docker compose up -d --build
# 浏览器访问 http://localhost
# 用 cjx + 你在 .env 中设置的密码登录
```

## 生产部署（阿里云 / Ubuntu 22.04）

一行命令搞定 Docker / 防火墙 / HTTPS / 自动备份。详见 [`deploy/README.md`](deploy/README.md)：

```bash
curl -fsSL https://raw.githubusercontent.com/githubcjx/E-commerce-data-dashboard/main/deploy/install.sh | sudo bash
```

## 本地开发

后端：

```bash
cd backend
python -m venv .venv && . .venv/Scripts/activate   # Windows
pip install -r requirements.txt
cp .env.example .env  # 修改 DATABASE_URL 指向本地 Postgres
uvicorn app.main:app --reload
```

前端：

```bash
cd frontend
npm install
npm run dev  # http://localhost:5173 ，已配置 /api 代理到 :8000
```

## 目录结构

```
backend/
  app/
    api/            auth.py, import_api.py, dashboard.py, layout.py
    services/       excel_parser.py（流式 + 清洗）, import_service.py（UPSERT）, dashboard_service.py（聚合）
    models.py       sales_records / import_batches / dashboard_layouts
    schemas.py      Pydantic 响应模型
    security.py     JWT 团队 Token
    main.py         FastAPI 入口
  Dockerfile

frontend/
  src/
    api/            axios 封装 + 各模块 API
    components/     KpiCard, DraggableGrid, TrendPanel/TrendChart, CategoryTable, FilterBar, ...
    views/          Login, Dashboard, Import
    stores/         Pinia: dashboard, ui
    styles/         tokens.css + app.css（来自设计稿）
    router/         登录守卫
  Dockerfile + nginx.conf

design/             原始设计稿（HTML/CSS/JS 原型）
docker-compose.yml
```

## 关键决策对齐

- **去重粒度**：`(shop_code, date, sku)` UNIQUE 约束 + `ON CONFLICT DO UPDATE`（PostgreSQL 原生 UPSERT）
- **百分比清洗**：`8.97%` → `0.0897` 存库，展示时由前端格式化
- **数据规模**：通过 openpyxl `read_only=True` 流式逐行解析，10 万行级文件不爆内存
- **环比定义**：日→昨天；周→上周；月→上月
- **趋势跨度**：日 10 天 / 周 12 周 / 月 12 个月
- **聚合方式**：率类指标用总额比值计算（避免 Simpson's paradox）
- **登录方式**：团队访问密码 → JWT（7 天有效），存于 `localStorage`
- **布局保存**：团队共享 `dashboard_layouts.default` 一条记录

## API 一览

所有数据接口均要求 `Authorization: Bearer <token>`，返回统一信封 `{ code, data, msg }`。

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/login` | 团队密码校验 |
| POST | `/api/import/upload` | 上传 Excel，返回 batch_id |
| GET  | `/api/import/batches/{id}` | 查询批次状态 |
| GET  | `/api/import/batches` | 导入历史 |
| DELETE | `/api/import/batches/{id}` | 按批次回滚 |
| GET  | `/api/dashboard/kpi` | 8 个 KPI + 上期对比 + 迷你序列 |
| GET  | `/api/dashboard/trend` | 趋势图数据 |
| GET  | `/api/dashboard/category` | 类目汇总表 |
| GET  | `/api/dashboard/filters` | 筛选下拉选项 |
| GET  | `/api/layout` | 读看板布局 |
| PUT  | `/api/layout` | 保存看板布局 |

公共查询参数：`end_date`, `granularity (day/week/month)`, `shop_code`, `owner`, `category`（`all` 表示不筛选）。

## 验收

1. `docker compose up -d --build` 启动后访问 `http://localhost`
2. 用 `ec2026` 登录 → 进入「导入」上传 Excel（参考 `数据源.xlsx` 真实样本）
3. 切换到「看板」查看 8 张 KPI、趋势图、类目汇总
4. 拖动 KPI 卡片或面板可重排，「重置布局」恢复默认
5. 在「导入」记录中可对任一批次「回滚」

## 已知后续工作

- M2/M3 升级：单文件超 10 万行可切换 Celery + Redis（接口已隔离在 `services/import_service.py`）
- 数据量上千万：增加 `daily_summary` 预聚合表（凌晨定时任务）
- 用户体系：当前为团队共享密码，可扩展为账号 + 角色
