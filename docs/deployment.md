# 部署指南（本机 / Docker / 云主机）

## 1. 本机运行

```bash
cd Argument-Atlas
python -m venv .venv

# Windows
.venv\Scripts\pip install -r requirements-dev.txt
# macOS / Linux
# source .venv/bin/activate && pip install -r requirements-dev.txt

python run.py
```

打开 `http://127.0.0.1:8000`。

- 没有 `.env` 时默认 Mock 模式，无需 API Key；
- 需要真实模型时复制 `.env.example` 为 `.env`，填入 `DEEPSEEK_API_KEY`；
- 健康检查：`curl http://127.0.0.1:8000/api/health`。

### 1.1 临时公网演示

最省事的方式是用隧道（Cloudflare Tunnel、ngrok 等）把本地 8000 端口临时暴露。**不要**在没有访问控制的情况下长期暴露，因为本应用没有登录系统。

如果必须临时公开：

- 给隧道加访问密码（Cloudflare Access）；
- 或在前面加一层 Nginx Basic Auth（见 §3）；
- 演示结束后立即关闭隧道；
- 不要使用存有敏感数据的 `.env` / 数据库。

## 2. Docker

项目提供 `Dockerfile` 与 `docker-compose.yml`。

```bash
# 离线 Mock（不需要 Key）
ATLAS_MODE=mock docker compose up -d --build

# 真实模型：在 .env 中配置 DEEPSEEK_API_KEY
docker compose up -d --build

curl http://127.0.0.1:8000/api/health
```

Compose 会把以下变量注入容器：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `ATLAS_MODE` | `auto` | `auto` / `live` / `mock` |
| `ATLAS_MODEL` | `deepseek-flash` | 模型名 |
| `DEEPSEEK_API_KEY` | 空 | Key；只从宿主环境注入，不进入镜像 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | OpenAI 兼容端点 |
| `ATLAS_DB` | `/data/atlas.db` | 容器内数据库路径 |

数据持久化在 Docker volume `atlas-data` 中。容器内以非 root 用户运行；`.dockerignore` 排除了 `.env`、`atlas.db` 与测试/文档。

> 说明：开发机没有安装 Docker，因此 Dockerfile/Compose **未在本机实际构建**。GitHub Actions 的 `docker` job 会在 push 时执行 `docker build` 并做健康检查 + NDJSON 拆解烟测；首次 push 后以 Actions 结果为准。

## 3. Nginx 反向代理

示例配置：[`deploy/nginx.conf`](../deploy/nginx.conf)。

关键点：

- 本项目用 **NDJSON**（不是 SSE）返回流式事件，必须关闭代理缓冲：
  - `proxy_buffering off;`
  - `proxy_cache off;`
  - `proxy_read_timeout 300s;`
  - `add_header X-Accel-Buffering no;`
- `client_max_body_size 1m`：只接收文本（上限 12,000 字符），不需要大文件上传；
- 同源部署，不需要 CORS；
- 健康检查 `/api/health` 可关闭访问日志。

### 3.1 加 Basic Auth（可选）

```bash
sudo apt-get install apache2-utils
sudo htpasswd -c /etc/nginx/.htpasswd demo
```

在 `location /` 中加入：

```nginx
auth_basic "Argument Atlas";
auth_basic_user_file /etc/nginx/.htpasswd;
```

### 3.2 TLS

用 certbot 或云厂商证书：

```bash
sudo certbot --nginx -d argument-atlas.example.com
```

生产环境只开放 80/443；应用端口 8000 只监听本机或容器网络。

## 4. 配置

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | 空 | 真实模型 Key；为空时自动 Mock |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | OpenAI 兼容端点 |
| `ATLAS_MODE` | `auto` | `auto` / `live` / `mock` |
| `ATLAS_MODEL` | `deepseek-flash` | 模型名 |
| `ATLAS_DB` | `atlas.db` | SQLite 路径；Docker 中为 `/data/atlas.db` |
| `ATLAS_MIN_INPUT_CHARS` | `30` | 最小输入长度 |
| `ATLAS_MAX_INPUT_CHARS` | `12000` | 最大输入长度 |
| `ATLAS_HOST` | `127.0.0.1` | 本机监听地址（Docker 用 0.0.0.0） |
| `ATLAS_PORT` | `8000` | 端口 |
| `ATLAS_NO_BROWSER` | 空 | `1` 时不自动打开浏览器 |

安全要求：

- `.env` 不提交、不打包进镜像；
- 不要把 Key 写进命令行历史、日志或前端；
- 如果 Key 曾经泄露，立即在 DeepSeek 控制台轮换。

## 5. 数据与备份

SQLite 数据库在 `ATLAS_DB` 指定位置（Docker 容器内为 `/data/atlas.db`）。建议先停服务或使用 SQLite backup API：

```python
import sqlite3

source = sqlite3.connect("/data/atlas.db")
target = sqlite3.connect("/data/backup-atlas.db")
source.backup(target)
target.close()
source.close()
```

恢复时停止服务，替换数据库文件，再启动。WAL 模式下还需要处理 `-wal` / `-shm`；最稳妥的做法是停服务后复制整个数据目录。

## 6. 回滚

当前没有数据库迁移框架，回滚策略保持简单：

1. 发布前做一次数据库备份；
2. 镜像使用不可变 tag（例如 `argument-atlas:2026-11-18`），不要只依赖 `latest`；
3. 回滚时切回旧 tag；
4. 如果 schema 有变化，先恢复对应备份，再启动旧版本。

## 7. 云主机清单

1. 安装 Docker / Compose；
2. 拉取代码，创建 `.env`（或使用云密钥服务注入环境变量）；
3. `docker compose up -d --build`；
4. 安装 Nginx，套用 `deploy/nginx.conf`；
5. 配置 TLS 与访问控制；
6. 只开放 80/443，限制 8000 端口；
7. 配置健康检查与日志轮转；
8. 定期备份数据卷。

本项目**没有实际部署到云主机**；以上是可复现的部署步骤，不构成已部署声明。

## 8. 安全检查

- [ ] `.env` 不在镜像/仓库中
- [ ] 公网访问有 Basic Auth / Access / SSO
- [ ] 8000 端口不直接暴露
- [ ] TLS 已启用
- [ ] 定期备份数据库，并验证过恢复
- [ ] 日志不包含 Key 或完整用户文本
- [ ] 明确告知用户：真实模式会把文本发送给模型供应商
- [ ] 需要多用户时先补身份、隔离与限流
