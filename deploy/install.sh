#!/usr/bin/env bash
#
# One-shot installer for the e-commerce data dashboard.
# Supports:
#   - Ubuntu 22.04 LTS / Debian 11+
#   - Alibaba Cloud Linux 3 / Anolis OS 8 / CentOS 7+ / Rocky / AlmaLinux / RHEL
#
# Usage (on your fresh server, as root or via sudo):
#
#   curl -fsSL https://raw.githubusercontent.com/githubcjx/E-commerce-data-dashboard/main/deploy/install.sh | sudo bash
#
# Or inspect first:
#
#   curl -fsSL https://raw.githubusercontent.com/githubcjx/E-commerce-data-dashboard/main/deploy/install.sh -o install.sh
#   less install.sh
#   sudo bash install.sh
#
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/githubcjx/E-commerce-data-dashboard.git}"
INSTALL_DIR="${INSTALL_DIR:-/opt/ec-dashboard}"

# ---- pretty output ----
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log()  { echo -e "${BLUE}[$(date +%H:%M:%S)]${NC} $*"; }
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}!${NC} $*"; }
die()  { echo -e "${RED}✗${NC} $*" >&2; exit 1; }

# ---- 0. root check ----
[ "$EUID" -eq 0 ] || die "请以 root 身份运行：sudo bash $0"

# ---- detect distro family ----
OS_ID=""; OS_ID_LIKE=""; OS_PRETTY=""
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS_ID="${ID:-}"
    OS_ID_LIKE="${ID_LIKE:-}"
    OS_PRETTY="${PRETTY_NAME:-$OS_ID}"
fi

FAMILY=""; PKG_MGR=""; FW=""
case "$OS_ID $OS_ID_LIKE" in
    *ubuntu*|*debian*)
        FAMILY=debian; PKG_MGR=apt; FW=ufw
        ;;
    *alinux*|*anolis*|*rhel*|*centos*|*fedora*|*rocky*|*almalinux*)
        FAMILY=rhel
        command -v dnf &>/dev/null && PKG_MGR=dnf || PKG_MGR=yum
        FW=firewalld
        ;;
    *)
        warn "未识别的发行版：$OS_PRETTY (ID=$OS_ID, ID_LIKE=$OS_ID_LIKE)"
        read -p "尝试按 RHEL 家族（dnf）继续？[y/N] " yn </dev/tty
        [[ "$yn" =~ ^[Yy]$ ]] || exit 1
        FAMILY=rhel; PKG_MGR=dnf; FW=firewalld
        ;;
esac

ok "系统：$OS_PRETTY"
ok "包管理器：$PKG_MGR ｜ 防火墙：$FW"

# ---- memory check ----
MEM_MB=$(awk '/MemTotal/ {printf "%d", $2/1024}' /proc/meminfo)
if [ "$MEM_MB" -lt 1800 ]; then
    warn "服务器内存 ${MEM_MB} MB，构建前端时可能 OOM，建议 ≥ 2GB"
fi

# ---- 1. base deps ----
log "安装基础依赖（curl / git / openssl / firewall）..."
case "$FAMILY" in
    debian)
        DEBIAN_FRONTEND=noninteractive apt-get update -qq
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
            curl git ufw openssl ca-certificates >/dev/null
        ;;
    rhel)
        $PKG_MGR -y -q install curl git openssl ca-certificates >/dev/null
        $PKG_MGR -y -q install firewalld >/dev/null 2>&1 || true
        systemctl enable --now firewalld >/dev/null 2>&1 || true
        ;;
esac
ok "基础依赖就绪"

# ---- 2. Docker ----
if ! command -v docker &>/dev/null; then
    log "安装 Docker（可能要 2-3 分钟）..."
    case "$FAMILY" in
        debian)
            curl -fsSL https://get.docker.com | sh >/dev/null
            ;;
        rhel)
            # Try install dnf plugins (or yum-utils on older systems)
            $PKG_MGR -y -q install dnf-plugins-core >/dev/null 2>&1 \
                || $PKG_MGR -y -q install yum-utils >/dev/null 2>&1 || true

            # Prefer Aliyun mirror (faster from China), fall back to upstream
            REPO_FILE=/etc/yum.repos.d/docker-ce.repo
            if ! curl -fsSL --max-time 15 \
                http://mirrors.aliyun.com/docker-ce/linux/centos/docker-ce.repo \
                -o "$REPO_FILE" 2>/dev/null; then
                curl -fsSL https://download.docker.com/linux/centos/docker-ce.repo \
                    -o "$REPO_FILE"
            fi

            # Alibaba Cloud Linux / Anolis pin to RHEL 8 packages
            sed -i 's|$releasever|8|g' "$REPO_FILE"

            $PKG_MGR -y -q install docker-ce docker-ce-cli containerd.io \
                docker-buildx-plugin docker-compose-plugin >/dev/null \
                || die "Docker 安装失败，看上面的日志"
            systemctl enable --now docker
            ;;
    esac
fi
ok "$(docker --version)"

if ! docker compose version &>/dev/null; then
    log "安装 Docker Compose 插件..."
    case "$FAMILY" in
        debian) DEBIAN_FRONTEND=noninteractive apt-get install -y -qq docker-compose-plugin >/dev/null ;;
        rhel)   $PKG_MGR -y -q install docker-compose-plugin >/dev/null ;;
    esac
fi
ok "$(docker compose version)"

# ---- 2.5 Docker registry mirrors (mandatory in China) ----
# Without these, pulling from registry-1.docker.io times out on most servers
# hosted in mainland China. Users with their own Aliyun personal mirror can
# edit /etc/docker/daemon.json afterwards — we only set defaults if the file
# isn't already there.
if [ ! -f /etc/docker/daemon.json ]; then
    log "配置 Docker 镜像加速器（公共镜像，国内拉镜像不再超时）..."
    mkdir -p /etc/docker
    cat > /etc/docker/daemon.json <<'JSON'
{
    "registry-mirrors": [
        "https://docker.m.daocloud.io",
        "https://dockerhub.icu",
        "https://docker.1panel.live",
        "https://hub.rat.dev"
    ]
}
JSON
    systemctl restart docker
    sleep 2
    ok "镜像加速器已配置"
    warn "如果以上 4 个镜像都被墙，建议替换为阿里云个人加速器："
    warn "    https://cr.console.aliyun.com/cn-hangzhou/instances/mirrors"
else
    ok "/etc/docker/daemon.json 已存在，跳过镜像加速配置"
fi

# ---- 3. firewall ----
log "配置 $FW 开放 22 / 80 / 443..."
case "$FW" in
    ufw)
        ufw allow 22/tcp  >/dev/null 2>&1 || true
        ufw allow 80/tcp  >/dev/null 2>&1 || true
        ufw allow 443/tcp >/dev/null 2>&1 || true
        ufw --force enable >/dev/null 2>&1 || true
        ;;
    firewalld)
        firewall-cmd --permanent --add-service=ssh   >/dev/null 2>&1 || true
        firewall-cmd --permanent --add-port=80/tcp   >/dev/null 2>&1 || true
        firewall-cmd --permanent --add-port=443/tcp  >/dev/null 2>&1 || true
        firewall-cmd --reload >/dev/null 2>&1 || true
        ;;
esac
ok "$FW 已开放 22 / 80 / 443"
warn "记得同时在【阿里云控制台 → 实例 → 防火墙】也开放 80 / 443，那是另一层！"

# ---- 4. clone / pull ----
if [ -d "$INSTALL_DIR/.git" ]; then
    log "$INSTALL_DIR 已存在，拉取最新代码..."
    cd "$INSTALL_DIR" && git pull --ff-only
else
    log "克隆仓库到 $INSTALL_DIR..."
    git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# ---- 5. .env ----
if [ -f .env ]; then
    ok ".env 已存在，跳过交互配置（如需重置请先删除 $INSTALL_DIR/.env）"
else
    echo
    echo "============================================"
    echo "  生产环境参数（这一步只做一次）"
    echo "============================================"
    echo

    read -p "你的域名（已解析到本服务器；留空就用 IP + HTTP）: " DOMAIN </dev/tty
    read -p "平台管理员用户名 [cjx]: " ADMIN_USER </dev/tty
    ADMIN_USER=${ADMIN_USER:-cjx}

    while true; do
        read -s -p "平台管理员密码（至少 8 位，登录后用这个）: " ADMIN_PASS </dev/tty
        echo
        if [ ${#ADMIN_PASS} -lt 8 ]; then warn "密码至少 8 位，重试"; continue; fi
        read -s -p "再输入一次确认: " ADMIN_PASS2 </dev/tty
        echo
        if [ "$ADMIN_PASS" != "$ADMIN_PASS2" ]; then warn "两次输入不一致，重试"; continue; fi
        break
    done

    JWT_SECRET=$(openssl rand -hex 32)
    PG_PASS=$(openssl rand -hex 24)
    SITE_ADDRESS="${DOMAIN:-:80}"

    umask 077
    cat > .env <<EOF
# Generated by deploy/install.sh on $(date -u +%FT%TZ)
POSTGRES_PASSWORD=$PG_PASS
JWT_SECRET=$JWT_SECRET
PLATFORM_ADMIN_USERNAME=$ADMIN_USER
PLATFORM_ADMIN_PASSWORD=$ADMIN_PASS
SITE_ADDRESS=$SITE_ADDRESS
EOF
    chmod 600 .env
    ok ".env 已生成（权限 600）"
fi

# ---- 6. SELinux note ----
if command -v getenforce &>/dev/null && [ "$(getenforce)" = "Enforcing" ]; then
    warn "SELinux 处于 Enforcing 模式。Caddy 卷挂载已加 :Z 标签，应该没问题。"
    warn "若启动后 Caddy 报权限错误，可临时 'setenforce 0' 排查。"
fi

# ---- 7. build & up ----
log "构建并启动容器（首次约 3-5 分钟，下载镜像 + 构建前端）..."
COMPOSE="docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml"
$COMPOSE pull --quiet 2>/dev/null || true
$COMPOSE up -d --build

# ---- 8. wait for backend ----
log "等待后端服务就绪（最多 2 分钟）..."
for i in {1..60}; do
    if $COMPOSE exec -T backend python -c \
        "import urllib.request,sys; urllib.request.urlopen('http://localhost:8000/api/health',timeout=2)" \
        >/dev/null 2>&1; then
        ok "后端健康检查通过"
        break
    fi
    if [ "$i" -eq 60 ]; then
        warn "后端 2 分钟内未就绪，用 'docker compose logs backend' 排查"
    fi
    sleep 2
done

# ---- 8b. backup cron ----
if [ -x "$INSTALL_DIR/deploy/setup-cron.sh" ]; then
    log "注册每日 03:00 自动备份..."
    bash "$INSTALL_DIR/deploy/setup-cron.sh" || warn "备份 cron 安装失败，可稍后手动跑 deploy/setup-cron.sh"
fi

# ---- 9. summary ----
SITE_ADDR=$(grep ^SITE_ADDRESS .env | cut -d= -f2)
ADMIN_USER=$(grep ^PLATFORM_ADMIN_USERNAME .env | cut -d= -f2)
PUBLIC_IP=$(curl -fsS --max-time 5 https://ifconfig.me 2>/dev/null || \
            curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null || \
            echo "<你的服务器 IP>")

echo
echo "============================================"
echo "  🎉 部署完成"
echo "============================================"
echo
if [ "$SITE_ADDR" != ":80" ]; then
    echo "  访问地址：    https://$SITE_ADDR"
    echo "                Caddy 首次访问时自动申请 Let's Encrypt（10-30s）"
else
    echo "  访问地址：    http://$PUBLIC_IP"
    echo "                （未配域名，HTTP-only。后续可重跑本脚本切到 HTTPS）"
fi
echo
echo "  登录账号：    $ADMIN_USER  /  （你刚才设置的密码）"
echo
echo "  安装目录：    $INSTALL_DIR"
echo
echo "  常用命令（在 $INSTALL_DIR 目录下）："
echo "    日志：     docker compose logs -f"
echo "    升级：     git pull && $COMPOSE up -d --build"
echo "    重启：     $COMPOSE restart"
echo "    备份 DB：  bash deploy/backup.sh"
echo
echo "  详细手册：    $INSTALL_DIR/deploy/README.md"
echo "============================================"
