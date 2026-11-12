# 大狗嚼电竞管理系统 - Docker 部署指南

> 最新版本：v5.1  
> 更新时间：2026-11-02

---

## 一、快速启动（5分钟）

### 1. 环境准备

- Docker Desktop（Windows/Mac）或 Docker Engine（Linux）
- Docker Compose V2（新版Docker已内置）
- 确保 80 / 3307 / 7474 / 7687 / 8000 端口未被占用

### 2. 配置环境变量

在项目根目录创建 `.env` 文件：

```env
# AI 服务配置（默认已配置DeepSeek，可自行替换）
AI_API_KEY=sk-填入你自己的APIKey
AI_MODEL=deepseek-chat
AI_BASE_URL=https://api.deepseek.com/v1/chat/completions

# MySQL 配置（容器内端口，映射到宿主机3307避免和本地MySQL冲突）
MYSQL_ROOT_PASSWORD=root123456
MYSQL_DATABASE=game_escort_club

# Neo4j 配置
NEO4J_AUTH=neo4j/neo4j123456
```

### 3. 一键启动全部服务

```bash
docker compose up -d
```

首次启动会自动：
- 拉取 MySQL 8.0 / Neo4j 5 / Nginx alpine 镜像
- 构建后端 FastAPI 镜像
- 自动创建数据库表、初始化测试账号
- 启动全部服务容器

启动完成大约需要 3-5 分钟（视网络情况）。

### 4. 验证启动状态

```bash
# 查看所有容器状态
docker compose ps

# 预期输出：
# NAME                IMAGE               STATUS          PORTS
# dgeq-backend        game_backend        Up 2 minutes    0.0.0.0:8000->8000/tcp
# dgeq-frontend       nginx:alpine        Up 2 minutes    0.0.0.0:80->80/tcp
# dgeq-mysql          mysql:8.0           Up 2 minutes    0.0.0.0:3307->3306/tcp
# dgeq-neo4j          neo4j:5-community   Up 2 minutes    0.0.0.0:7474->7474/tcp, 0.0.0.0:7687->7687/tcp
```

看到 4 个容器都是 `Up` 状态就说明部署成功了。

### 5. 访问系统

| 服务 | 地址 | 默认账号 |
|------|------|----------|
| 系统主入口 | http://localhost | 管理员/客服/老板/打手，密码均为123456 |
| 后端API文档 | http://localhost:8000/docs | - |
| Neo4j 知识图谱浏览器 | http://localhost:7474 | 账号 neo4j / 密码 neo4j123456 |
| MySQL 数据库 | localhost:3307 | 账号 root / 密码 root123456，库名 game_escort_club |

---

## 二、服务架构说明

```
用户浏览器
    │
    ▼
┌─────────┐    /api/*     ┌─────────┐
│ Nginx  │ ───────────▶ │ Backend │
│ (前端) │             │ FastAPI │
└─────────┘             └────┬────┘
                               │
               ┌───────────────┼───────────────┐
               ▼               ▼               ▼
          ┌─────────┐    ┌──────────┐    ┌──────────┐
          │  MySQL  │    │  Neo4j   │    │ DeepSeek │
          │  (业务库)│    │ (知识图谱)│    │  (AI接口)│
          └─────────┘    └──────────┘    └──────────┘
```

### 容器清单

| 容器名 | 镜像 | 作用 | 端口映射（宿主机→容器） |
|--------|------|------|------------------------|
| dgeq-frontend | nginx:alpine | 前端静态页面+反向代理 | 80:80 |
| dgeq-backend | 本地构建 | FastAPI 后端服务 | 8000:8000 |
| dgeq-mysql | mysql:8.0 | 业务数据存储 | 3307:3306 |
| dgeq-neo4j | neo4j:5-community | RAG知识图谱存储 | 7474:7474, 7687:7687 |

---

## 三、常用运维命令

### 启动/停止/重启

```bash
# 启动全部服务
docker compose up -d

# 停止全部服务
docker compose down

# 重启某个服务
docker compose restart backend

# 停止并删除数据卷（清空所有数据，慎用）
docker compose down -v
```

### 查看日志

```bash
# 查看后端实时日志
docker compose logs -f backend

# 查看最近100行日志
docker compose logs --tail 100 backend

# 查看Nginx前端日志
docker compose logs -f frontend
```

### 更新代码后重新部署

```bash
# 拉取最新代码
git pull

# 重新构建后端并启动
docker compose up -d --build backend

# 前端不需要构建，刷新浏览器即可
```

---

## 四、常见问题排查

### 1. 端口占用（最常见问题）

**问题**：启动报错 `ports are not available: bind: Only one usage of each socket address`

**原因**：本地已经安装了MySQL/Redis等服务占用了对应端口

**解决**：
- MySQL 3306冲突：本项目已经把容器MySQL映射到宿主机3307，不会冲突
- 80端口被占用：修改 `docker-compose.yml` 里 frontend 的 ports，改成 `8080:80`
- 改完后重启：`docker compose up -d`

### 2. 镜像下载慢/卡住

**解决**：配置国内Docker镜像源，在 Docker Desktop 设置 → Docker Engine 里添加：
```json
{
  "registry-mirrors": [
    "https://docker.m.daocloud.io",
    "https://dockerproxy.com"
  ]
}
```
重启Docker后重新执行 `docker compose up -d`

### 3. 其他人局域网访问不了

**解决**：
- 查看本机局域网IP：`ipconfig`（Windows）/ `ifconfig`（Linux/Mac）
- 确保前端Nginx的 `API_BASE` 配置为相对路径 `/api`，不要写 `localhost:8000`
- 局域网其他用户直接访问 `http://你的局域网IP` 即可
- 确认Windows防火墙放开80端口入站规则

### 4. AI客服不回复/报错

**排查步骤**：
```bash
# 1. 看后端日志
docker compose logs backend | grep -i error

# 2. 确认API Key可用
# 进入 AI设置 → 模型配置，点「测试连接」按钮
```

**常见原因**：
- API Key 额度用完
- 网络访问不了DeepSeek/千问接口
- 模型名写错（默认 deepseek-chat）

### 5. 本地开发和Docker同时运行

**解决**：
- Docker 后端默认占用 8000 端口
- 本地开发时设置环境变量：`$env:PORT=9000`，然后 `python main.py`
- 本地跑在 9000 端口，和Docker的8000错开，不会冲突

---

## 五、模型切换说明

系统默认使用 **DeepSeek V3**（`deepseek-chat`），支持随时在后台切换：

进入 **AI设置 → 模型配置** 页面，下拉选择即可，自动同步对应API地址：

| 模型选项 | 适用场景 |
|----------|----------|
| DeepSeek V3（推荐） | 日常对话，快且便宜，质量好 |
| DeepSeek R1 | 复杂推理问题，回答更慢但逻辑强 |
| Qwen Plus | 兼容阿里百炼接口，稳定 |
| Qwen Turbo | 追求最快响应速度 |

切换后立即生效，无需重启后端容器。

---

## 六、备份与数据恢复

### 备份MySQL数据

```bash
# 导出全部数据到本地文件
docker exec dgeq-mysql mysqldump -uroot -proot123456 game_escort_club > backup.sql
```

### 恢复数据

```bash
# 从备份文件恢复
docker exec -i dgeq-mysql mysql -uroot -proot123456 game_escort_club < backup.sql
```

### 数据存储位置

- MySQL 数据：Docker volume `dgeq_mysql_data`
- Neo4j 数据：Docker volume `dgeq_neo4j_data`
- 知识库文件：挂载在 `./kb_images`、`./bizhiku`、`./touxiangku` 目录

---

## 七、生产环境部署建议

1. 配置HTTPS证书，在Nginx层加SSL
2. 修改默认数据库密码和Neo4j密码，不要用默认弱密码
3. 配置定时任务自动备份数据库
4. 开放防火墙白名单，不要把3307/7474端口暴露到公网
5. 配置日志轮转，避免容器日志占满磁盘
