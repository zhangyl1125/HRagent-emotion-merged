---
name: hragent-docker
description: Docker Compose service management for HRagent-05. Use when starting, stopping, rebuilding, checking status, viewing logs, or troubleshooting the postgres/redis/mineru/backend/frontend services.
triggers:
  - docker compose
  - 启动服务
  - 重建
  - health check
  - 容器状态
  - 日志
  - postgres
  - redis
  - mineru
  - backend
  - frontend
scope: HRagent-05
---

# HRagent-05 Docker 服务管理

## 服务清单

| 服务 | 镜像/构建 | 宿主机端口 | 容器端口 | 容器内地址 |
|---|---|---|---|---|
| `postgres` | pgvector/pgvector:pg16 | 5432 | 5432 | `postgres:5432` |
| `redis` | redis:7-alpine | 6381 | 6379 | `redis:6379` |
| `mineru` | mineru_service/Dockerfile | 18000 | 8000 | `mineru:8000` |
| `backend` | backend/Dockerfile | 8111 | 8111 | `backend:8111` |
| `frontend` | frontend/Dockerfile | 8080, 8443 | 8080, 8443 | `frontend:8080` |

**持久化数据：**
- PostgreSQL 数据：Docker named volume `postgres_data`
- Redis 数据：`data/redis/`（已在 `.dockerignore` 中排除）
- 业务数据：`data/` 挂载到 backend 容器 `/app/data`

## 常用命令

### 查看状态

```bash
docker compose ps
```

### 启动服务

```bash
# 启动基础服务和前后端（最常用）
docker compose up -d postgres redis backend frontend

# 包含 MinerU（需要 GPU）
docker compose up -d postgres redis mineru backend frontend
```

### 重建单个服务

```bash
# 重建后端
docker compose build backend
docker compose up -d backend

# 重建前端
docker compose build frontend
docker compose up -d frontend
```

> **注意：** `docker compose up --build` 会触发所有服务重建，只在明确需要整体重建时使用。

### 查看日志

```bash
docker compose logs --tail=120 backend
docker compose logs --tail=120 frontend
docker compose logs -f backend    # 实时跟踪
```

### 健康检查

```bash
# 后端健康检查
curl -fsS http://localhost:8111/api/v1/health

# 前端 HTTPS 代理健康检查
curl -k -fsS https://localhost:8443/api/v1/health

# Redis 连通性
docker compose exec -T redis redis-cli ping
```

## 操作边界

1. **只操作 HRagent-05 容器**，不操作 HRagent-06 或其他用户的容器。
2. **不删除 `data/` 中的文件**（上传文件、解析结果、Redis/PostgreSQL 持久化数据），除非用户明确要求。
3. **不随意修改服务名、端口、volume、网络配置**，除非当前任务明确要求。
4. **不执行 `docker compose down -v`** 等破坏性操作，除非用户明确要求并确认影响。
5. 涉及网络、Docker、远端 API 或容器状态的命令，**执行前说明目的和影响**。
