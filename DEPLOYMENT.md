# Harness 引擎部署指南

本文档介绍如何使用 Docker / Docker Compose 将 Harness 引擎部署到单机或云服务器（阿里云 / 腾讯云）。

---

## 1. 环境要求

| 项目 | 最低配置 |
|------|----------|
| CPU | 2 核 |
| 内存 | 4 GB（推荐 8 GB，需运行 Ollama 时另计） |
| 磁盘 | 20 GB SSD |
| 系统 | Linux（推荐 Ubuntu 22.04）或 Windows + Docker Desktop |
| 软件 | Docker 24+、Docker Compose v2 |

> **Windows 开发机**：需在 Docker Desktop → Settings → Resources → File Sharing 中共享项目目录（如 `C:\Users\guang`），否则卷挂载可能失败。

---

## 2. 快速开始（本地 / 测试）

### 2.1 克隆与配置

```bash
cd C:\Users\guang   # 或你的项目路径
cp .env.example .env
```

编辑 `.env`，**必须**修改：

```bash
# 生成随机密钥
python -c "import secrets; print(secrets.token_urlsafe(48))"
# 写入 .env
SECRET_KEY=<生成的密钥>
ADMIN_PASSWORD=<强密码>
```

### 2.2 启动服务

```bash
docker compose up -d --build
```

默认使用 `deploy/nginx.http.conf`（HTTP 80 端口，无 SSL），服务包括：

| 服务 | 说明 | 内部端口 |
|------|------|----------|
| `web` | Flask Web UI + 管理后台 | 7860 |
| `api` | FastAPI REST API | 8000 |
| `nginx` | 反向代理 | 80 → 对外 |

### 2.3 验证

```bash
# 健康检查
curl http://localhost/health
# 期望: {"status":"ok","version":"1.0.0"}

# 查看日志（输出到 stdout，便于 docker logs 收集）
docker compose logs -f web

# 使用 .env 中的 ADMIN_USERNAME / ADMIN_PASSWORD 登录
# 浏览器访问 http://localhost/auth/login
```

---

## 3. 生产环境部署（云服务器）

以下以 **阿里云 ECS / 腾讯云 CVM** 为例。

### 3.1 安全组 / 防火墙

仅开放：

| 端口 | 用途 | 建议 |
|------|------|------|
| 443 | HTTPS | 公网 |
| 80 | HTTP（重定向到 HTTPS） | 公网 |
| 22 | SSH | **限制来源 IP** |

**不要**对外开放数据库端口（5432 等）。Harness 默认 SQLite 数据保存在 Docker 卷 `harness-data` 中。

### 3.2 安装 Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
```

### 3.3 上传代码并配置

```bash
git clone <your-repo> /opt/harness
cd /opt/harness
cp .env.example .env
nano .env   # 填写 SECRET_KEY、ADMIN_PASSWORD、DOMAIN 等
```

### 3.4 启用 HTTPS（Let's Encrypt）

```bash
sudo apt install certbot
sudo certbot certonly --standalone -d your-domain.com

mkdir -p deploy/certs
sudo cp /etc/letsencrypt/live/your-domain.com/fullchain.pem deploy/certs/
sudo cp /etc/letsencrypt/live/your-domain.com/privkey.pem deploy/certs/
```

修改 `docker-compose.yml`：

1. 将 nginx 配置换为 `deploy/nginx.conf`
2. 取消 `443:443` 端口映射
3. 挂载 `./deploy/certs:/etc/nginx/certs:ro`

```yaml
nginx:
  ports:
    - "80:80"
    - "443:443"
  volumes:
    - ./deploy/nginx.conf:/etc/nginx/nginx.conf:ro
    - ./deploy/certs:/etc/nginx/certs:ro
```

续签证书（cron 示例，每月 1 日）：

```cron
0 3 1 * * certbot renew --quiet && docker compose -f /opt/harness/docker-compose.yml restart nginx
```

### 3.5 管理后台访问控制

`/admin/*` 包含敏感运营数据，建议：

- 通过公司 VPN 访问
- 或在 Nginx 中为 `/admin/` 配置 IP 白名单：

```nginx
location /admin/ {
    allow 10.0.0.0/8;
    deny all;
    proxy_pass http://harness_web/admin/;
}
```

### 3.6 启动

```bash
docker compose up -d --build
docker compose ps
```

---

## 4. 架构说明

```
                    ┌─────────────┐
  Internet :443 ──► │   Nginx     │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              ▼                         ▼
       ┌────────────┐           ┌────────────┐
       │  web:7860  │           │  api:8000  │
       │ Flask+gunicorn│        │  FastAPI   │
       └──────┬─────┘           └──────┬─────┘
              │                         │
              └────────────┬────────────┘
                           ▼
                  ┌─────────────────┐
                  │ harness-data 卷 │
                  │ harness.db      │
                  │ users/          │
                  └─────────────────┘
```

- 推理服务（Ollama）默认通过 `OLLAMA_BASE_URL=http://host.docker.internal:11434` 访问宿主机。
- 日志写入 **stdout/stderr**，使用 `docker compose logs` 查看，不在容器内落盘敏感信息。

---

## 5. 数据备份与恢复

### 5.1 备份

```bash
docker compose exec web sh /app/deploy/scripts/backup_db.sh
# 备份文件位于卷内 /app/data/backups/
```

或从宿主机卷目录复制（卷路径可用 `docker volume inspect harness_harness-data` 查看）。

### 5.2 恢复

```bash
docker compose exec web sh /app/deploy/scripts/restore_db.sh /app/data/backups/harness_YYYYMMDD_HHMMSS.db
docker compose restart web api
```

### 5.3 定时备份（cron）

```cron
0 2 * * * docker compose -f /opt/harness/docker-compose.yml exec -T web sh /app/deploy/scripts/backup_db.sh
```

---

## 6. 监控与日志

```bash
# 实时日志
docker compose logs -f web api nginx

# 健康检查
docker compose exec web python /app/deploy/healthcheck.py
echo $?   # 0 表示健康

# 镜像漏洞扫描（建议定期执行）
docker scan harness-engine:latest
# 或: trivy image harness-engine:latest
```

生产环境请确保：

- `DEBUG=false`
- `FLASK_ENV=production`
- 不在日志中打印密码、token、数据库连接串

---

## 7. 升级指南

```bash
cd /opt/harness
git pull
docker compose build --no-cache
docker compose up -d
docker compose exec web python /app/deploy/scripts/init_db.py  # 如有 schema 变更
```

升级前请先执行备份。

---

## 8. 切换 PostgreSQL（可选）

当用户量增大时，可在 `docker-compose.yml` 中取消 `postgres` 服务注释，并设置：

```env
DATABASE_URL=postgresql+psycopg2://harness:密码@postgres:5432/harness
```

需在 `requirements.txt` 增加 `psycopg2-binary`，并迁移数据。

---

## 9. 常见问题

### Q: `docker compose up` 后 /health 返回 502？

等待 `web` 服务健康检查通过：`docker compose ps`，状态应为 `healthy`。

### Q: SECRET_KEY 未设置导致启动失败？

确保 `.env` 存在且 `docker compose` 能读取；不要将真实 `.env` 提交到 Git。

### Q: Windows 下卷挂载权限错误？

在 Docker Desktop 中共享驱动器，或以管理员身份运行 Docker Desktop。

### Q: 如何创建额外管理员？

```bash
docker compose exec web python web_ui.py create-admin
```

### Q: 自签名证书测试 HTTPS？

```bash
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout deploy/certs/privkey.pem -out deploy/certs/fullchain.pem \
  -subj "/CN=localhost"
```

然后切换为 `deploy/nginx.conf` 并映射 443 端口。

---

## 10. 测试清单

| 检查项 | 命令 / 操作 |
|--------|-------------|
| 健康检查 200 | `curl http://localhost/health` |
| 未登录访问 /admin 重定向 | 浏览器访问 `/admin/` |
| 管理员登录 | 使用 `.env` 中 `ADMIN_*` |
| 数据持久化 | `docker compose down` 后 `up`，数据仍在 |
| 日志可见 | `docker compose logs web` |
| .env 未打入镜像 | 构建后 `docker run --rm harness-engine:latest ls -la /app/.env` 应不存在 |

---

## 11. 相关文件

| 文件 | 说明 |
|------|------|
| `Dockerfile` | 多阶段构建，非 root 用户 `harness` |
| `docker-compose.yml` | 服务编排 |
| `deploy/entrypoint.sh` | 启动入口（迁移 DB、创建管理员） |
| `deploy/nginx.conf` | 生产 HTTPS 配置 |
| `deploy/nginx.http.conf` | 本地 HTTP 配置 |
| `deploy/scripts/init_admin.py` | 从环境变量创建管理员 |
