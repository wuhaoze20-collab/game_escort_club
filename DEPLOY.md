# 大狗嚼电竞管理系统 - Docker 部署指南

## 快速启动

### 1. 配置 API Key

在项目根目录创建 `.env` 文件，填入通义千问 API Key：

```env
DASHSCOPE_API_KEY=sk-你的真实key
```

### 2. 启动全部服务

```bash
docker compose up -d
```

首次启动会自动构建后端镜像并拉取 MySQL / Neo4j / Nginx 镜像，大约需要 3-5 分钟。

### 3. 查看启动状态

```bash
# 查看所有服务状态
docker compose ps

# 查看后端日志（确认数据库建表完成）
docker compose logs -f backend
```

看到 `Uvicorn running on http://0.0.0.0:8000` 就说明后端启动成功了。

### 4. 访问系统

| 服务 | 地址 | 说明 |
|------|------|------|
| 前端 | http://localhost | 主入口（老板/打手/管理员） |
| 后端 API | http://localhost:8000/docs | FastAPI 自动文档 |
| Neo4j 浏览器 | http://localhost:7474 | 账号 neo4j / 密码 neo4j123456 |
| MySQL | localhost:3306 | 账号 game_escort / 密码 123456 |

## 服务架构

```
浏览器
  │
  ▼
┌─────────┐     /api/*      ┌─────────┐
│  Nginx  │ ──────────────▶ │ Backend │
│ (前端)  │                 │FastAPI  │
└─────────┘                 └────┬────┘
                                  │
                    ┌─────────────┼─────────────┐
                    ▼             ▼             ▼
                ┌───────┐   ┌─────────┐  ┌──────────┐
                │ MySQL │   │  Neo4j  │  │ 通义千问  │
                │ 8.0   │   │  5.x    │  │  API     │
                └───────┘   └─────────┘  └──────────┘
```

## 常用命令

```bash
# 停止服务（保留数据）
docker compose down

# 停止并删除数据（谨慎！）
docker compose down -v

# 重启后端（改了代码后）
docker compose restart backend

# 重新构建后端镜像（改了 requirements 后）
docker compose up -d --build backend

# 进入后端容器调试
docker compose exec backend bash
```

## 数据持久化

所有数据都保存在 Docker Volume 中，删除容器不会丢数据：

| Volume | 内容 |
|--------|------|
| `mysql_data` | MySQL 数据库文件 |
| `neo4j_data` | Neo4j 图谱数据 |
| `chroma_data` | Chroma 向量库索引 |
| `qdrant_data` | Qdrant 向量库索引 |

## 默认账号

系统启动时会自动 seed 默认账号：
- 管理员：`guanliyuan`
- 客服：`kefu`
- 老板：`laoban01` ~ `laoban05`
- 打手：`dashou01` ~ `dashou05`

密码统一为 `123456`（生产环境请修改）。
