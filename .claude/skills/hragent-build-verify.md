---
name: hragent-build-verify
description: Standard build-and-verify workflow for HRagent-05. Use after making any code changes to backend or frontend. Covers Docker rebuild, service restart, health checks, and Redis verification.
triggers:
  - 构建
  - 验证
  - build
  - verify
  - health check
  - 修改完成
  - 测试
  - compileall
scope: HRagent-05
---

# HRagent-05 构建与验证工作流

## 后端改动后的标准验证

```bash
# 1. Python 编译检查
python -m compileall backend

# 2. 重建并启动
docker compose build backend
docker compose up -d backend

# 3. 等待启动完成后健康检查
sleep 3
curl -fsS http://localhost:8111/api/v1/health

# 4. 运行相关测试（如有）
pytest tests/ -q -x
```

## 前端改动后的标准验证

```bash
# 1. TypeScript 编译检查
cd frontend && npm run build

# 2. 重建并启动
cd ..
docker compose build frontend
docker compose up -d frontend

# 3. HTTPS 代理健康检查
curl -k -fsS https://localhost:8443/api/v1/health
```

## Redis 相关改动后的验证

```bash
# 基础连通性
docker compose exec -T redis redis-cli ping

# 预期输出：PONG
```

## 完整验证流程（较大改动）

```bash
# 1. Python 编译
python -m compileall backend

# 2. 前端 TypeScript 编译
cd frontend && npm run build && cd ..

# 3. 重建所有服务
docker compose build backend frontend
docker compose up -d backend frontend

# 4. 健康检查
curl -fsS http://localhost:8111/api/v1/health
curl -k -fsS https://localhost:8443/api/v1/health
docker compose exec -T redis redis-cli ping

# 5. 确认所有服务运行正常
docker compose ps
```

## 验证失败时的输出规范

如果无法在当前环境完成构建、启动或接口测试，最终回复必须明确说明：

```markdown
## 未验证项
- **未执行命令**：xxx
- **原因**：xxx（如：无 Docker 环境、GPU 不可用、网络不通）
- **风险**：xxx
- **建议下一步**：xxx
```

## 注意事项

1. **后端启动依赖** postgres 和 redis 先 healthy，如果 `docker compose up -d backend` 长时间卡住，先检查依赖服务状态。
2. **前端构建**依赖 Node.js 和 npm，确保 Docker 能拉取 `node:22-alpine` 基础镜像。
3. **MinerU 服务**非必须，除非当前需求涉及文档解析。
4. 后端容器启动时会自动尝试导入 `data/employee_database/employees.xlsx`，文件不存在时跳过（看日志确认）。
5. 如果 build 失败，先用 `docker compose logs --tail=50 <service>` 查看错误原因。
