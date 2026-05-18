# 生产部署手册

> 一行命令把整套系统跑起来。包含 PostgreSQL、后端、前端、Caddy 自动 HTTPS、防火墙、备份。
>
> **支持的发行版**：Ubuntu 22.04 / Debian 11+ / **Alibaba Cloud Linux 3** / Anolis OS / CentOS 7+ / Rocky / AlmaLinux / RHEL

## 0. 一键部署 TL;DR

```bash
curl -fsSL https://raw.githubusercontent.com/githubcjx/E-commerce-data-dashboard/main/deploy/install.sh | sudo bash
```

按提示输入：
1. **域名**（可选）：如 `dashboard.example.com`。**留空就用 IP + HTTP**
2. **平台管理员用户名**：默认 `cjx`
3. **平台管理员密码**（至少 8 位，输两次确认）

5-10 分钟后访问域名（或 IP）即可。

---

## 1. 前置准备（10 分钟）

### 1.1 买服务器

阿里云 → 轻量应用服务器 → 选**经典应用镜像 "Docker"** 或纯净 **Ubuntu 22.04 LTS**

| 配置项 | 推荐 |
|---|---|
| 套餐 | 2核 4G（¥60-100/月） |
| 镜像 | Ubuntu 22.04 LTS 或 "Docker 应用镜像" |
| 系统盘 | 60G |
| 流量 | 1-5M 带宽 |

### 1.2 开放防火墙端口（**关键**）

阿里云控制台 → 你的实例 → **防火墙** → 添加规则：

| 应用 | 协议 | 端口 |
|---|---|---|
| SSH | TCP | 22 |
| HTTP | TCP | 80 |
| HTTPS | TCP | 443 |

> 阿里云上**两层**防火墙：阿里云控制台的安全组 + 服务器内的 ufw（脚本会自动配）。两层都得开。

### 1.3 域名（可选但强烈建议）

- 任意注册商买的域名都行（万网 / Namecheap / Cloudflare）
- 加一条 **A 记录**：`@` 或 `dashboard` → 你的服务器公网 IP
- `dig +short 你的域名` 能返回正确 IP 后再跑安装脚本（一般 5-30 分钟 DNS 生效）

### 1.4 SSH 登录服务器

阿里云控制台给你一个公网 IP 和初始密码（或绑定 SSH 密钥）。本机执行：

```bash
ssh root@<服务器 IP>
```

---

## 2. 跑安装脚本

```bash
curl -fsSL https://raw.githubusercontent.com/githubcjx/E-commerce-data-dashboard/main/deploy/install.sh | sudo bash
```

脚本会按顺序做这些事：

1. 检查系统（Ubuntu / Debian、内存 ≥ 1.8GB）
2. 装 Docker + Docker Compose 插件
3. 配 ufw 防火墙开 22/80/443
4. 把仓库 clone 到 `/opt/ec-dashboard`
5. 交互式问你域名 / 管理员账号 / 密码
6. 自动生成强 `JWT_SECRET`（64 hex）和 `POSTGRES_PASSWORD`（48 hex）
7. 写 `.env` 到 `/opt/ec-dashboard/.env`（权限 600，仅 root 可读）
8. `docker compose up -d --build` 拉镜像 + 构建前端 + 启动 4 个容器：
   - **db**：PostgreSQL 15
   - **backend**：FastAPI + uvicorn
   - **frontend**：nginx 提供 SPA 静态文件
   - **caddy**：公网反代 + 自动 HTTPS（Let's Encrypt）
9. 等后端健康检查通过
10. 打印访问地址和登录账号

### 不放心一键脚本？手动等价命令

```bash
# 装 Docker
curl -fsSL https://get.docker.com | sudo sh

# 装 ufw
sudo apt update && sudo apt install -y ufw
sudo ufw allow 22,80,443/tcp && sudo ufw --force enable

# clone
sudo git clone https://github.com/githubcjx/E-commerce-data-dashboard.git /opt/ec-dashboard
cd /opt/ec-dashboard

# .env
sudo cp .env.example .env
sudo nano .env
#   ↓ 把这几个改了：
#   POSTGRES_PASSWORD=<openssl rand -hex 24>
#   JWT_SECRET=<openssl rand -hex 32>
#   PLATFORM_ADMIN_PASSWORD=<你的强密码>
#   SITE_ADDRESS=你的域名   # 或留 :80 表示 HTTP-only

sudo chmod 600 .env

# 启动
sudo docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml up -d --build
```

---

## 3. 首次登录与使用

部署完后浏览器打开 `https://你的域名`：

1. 用 `cjx` / 你设的密码登录 → 自动进入**企业管理**页（`/admin/tenants`）
2. 点「**+ 新增企业**」，一次填好：
   - 企业短码：`acme`
   - 企业名称：`ACME 电商科技`
   - 首位管理员账号：`acme_admin`
   - 管理员密码：（线下交给企业）
3. 把 `acme_admin` / 密码交给企业方
4. 企业方登录后进入看板，**导入 Excel** 即可看到自己企业的数据

---

## 4. 日常运维

> 所有命令在 `/opt/ec-dashboard` 目录下执行。  
> 为节省篇幅，下面 `$COMPOSE` 代指：  
> `docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml`

### 4.1 查看日志

```bash
$COMPOSE logs -f                 # 所有服务实时
$COMPOSE logs -f backend         # 只看后端
$COMPOSE logs --tail=200 backend # 最近 200 行
$COMPOSE logs -f caddy           # 看 HTTPS 申请、路由
```

### 4.2 升级到最新代码

```bash
cd /opt/ec-dashboard
git pull
$COMPOSE up -d --build
```

### 4.3 重启 / 停止

```bash
$COMPOSE restart                  # 重启所有
$COMPOSE restart backend          # 只重启后端
$COMPOSE stop                     # 全部停（数据不丢）
$COMPOSE start                    # 重新拉起
$COMPOSE down                     # 删容器（数据卷保留）
$COMPOSE down -v                  # ⚠️ 删容器 + 删数据卷（永久删除全部数据！）
```

### 4.4 备份数据库

**手动备份**：

```bash
bash deploy/backup.sh
# 写到 /opt/ec-dashboard/backups/ec_dashboard_<日期>.sql.gz
```

**每日自动备份**（凌晨 3 点）：

```bash
sudo crontab -e
# 加这一行：
0 3 * * * /opt/ec-dashboard/deploy/backup.sh >> /opt/ec-dashboard/backups/backup.log 2>&1
```

备份脚本保留最近 14 天的 dump，旧的自动删除。

**异地备份**（强烈建议）：把 `backups/` 目录定期 rsync 到 OSS 或另一台机器：

```bash
# 例：每天 4 点 rsync 到阿里云 OSS（先 ossutil 配好）
0 4 * * * ossutil cp -r /opt/ec-dashboard/backups oss://your-bucket/ec-dashboard-backups/
```

### 4.5 恢复数据库

```bash
cd /opt/ec-dashboard

# 列出可用备份
ls -lh backups/

# ⚠️ 注意：会**覆盖**当前数据库！
gunzip -c backups/ec_dashboard_20260518-030000.sql.gz | \
    docker compose exec -T db psql -U postgres -d ec_dashboard
```

### 4.6 重置或修改 cjx 密码

**情况一**：DB 还是空的（从未启动过 / 刚 `down -v` 过）  
改 `.env` 里 `PLATFORM_ADMIN_PASSWORD`，再 `$COMPOSE up -d` 重启即可。

**情况二**：cjx 已经在 DB 里  
`.env` 的密码不再生效（防止重启偷改）。改 DB：

```bash
docker compose exec backend python - <<'PY'
import asyncio
from sqlalchemy import select
from app.db import SessionLocal
from app.models import User
from app.security import hash_password

async def main():
    async with SessionLocal() as s:
        u = (await s.execute(select(User).where(User.username == 'cjx'))).scalar_one()
        u.password_hash = hash_password('你的新密码')
        await s.commit()
        print('updated')

asyncio.run(main())
PY
```

### 4.7 看资源占用

```bash
docker stats                     # 实时 CPU / 内存 / IO
df -h                            # 磁盘
free -h                          # 内存
docker system df                 # Docker 占了多少
docker system prune              # 清理悬挂镜像 / 缓存（不动数据卷）
```

---

## 5. 故障排查

### 502 / 504：网关错误

```bash
$COMPOSE logs --tail=100 backend     # 后端是否健康
$COMPOSE logs --tail=100 caddy       # 路由 / 上游
$COMPOSE ps                          # 容器状态
docker compose exec backend curl -sf http://localhost:8000/api/health
```

### HTTPS 证书申请失败

- 检查域名是否解析到本机：`dig +short 你的域名`
- 检查 80 端口对外开放：`curl http://你的域名/`（Let's Encrypt 走 HTTP-01）
- 看 Caddy 日志：`$COMPOSE logs caddy | grep -iE 'error|tls|acme'`
- 速率限制：Let's Encrypt 每小时同一域名最多失败 5 次，挂久了就 `$COMPOSE restart caddy`

### 登录提示"账号或密码错误"

- 拼写 / 大小写
- cjx 密码用 4.6 重置
- 如果是企业用户，让所属企业的 admin 在「后台」给该用户改密

### 导入大 Excel 后端 OOM 被杀

- 服务器升级到 4G 内存
- 或调小 `backend/app/services/import_service.py` 里的 `BATCH_SIZE` 从 1000 → 500

### 升级后前端样式异常

浏览器强刷一次：`Ctrl + Shift + R`（清掉旧的 JS bundle 缓存）

### 数据库连不上 / `database is locked`

只在 SQLite 模式下会出现，生产用 PG 不会。如果你看到，说明 `.env` 里 `DATABASE_URL` 没指向 `postgresql+asyncpg://...`。

---

## 6. 安全建议

- `.env` 文件权限保持 `600`，永远别提交到 git（已在 `.gitignore`）
- 定期 `apt update && apt upgrade -y`
- SSH 关掉密码登录、改用密钥（阿里云控制台 → 密钥对）
- Caddy 自动续签证书，无需手动操作
- 每周看一眼 `docker compose logs --since=7d backend | grep -iE 'error|warn'`

---

## 7. 关于成本

| 项目 | 配置 | 月成本（¥） |
|---|---|---|
| 阿里云轻量应用服务器 | 2核 4G 5M | 60-100 |
| 域名 | `.com` 一年 | 7（折合每月） |
| 备份到 OSS（可选） | 10G | 5 |
| **合计** | | **约 ¥75-115/月** |

支撑 10-50 个企业租户、每企业 5-20 用户、累计百万级 sales_records 行没问题。规模继续往上：
- 数百企业 → 升 ECS + RDS PostgreSQL，建议 4核 8G + 100G SSD
- 累计千万行 → 加 `daily_summary` 预聚合表（按需求文档第 3.4 节决策 4 实现）
