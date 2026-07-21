# AGENTS.md
## 一定要遵守
DO NOT send optional commentary




## 可复用 Skills

以下 Skills 封装了本项目的核心工程模式和操作流程，可在对应场景下直接调用：

| Skill | 文件 | 用途 |
|---|---|---|
| `hragent-docker` | [.claude/skills/hragent-docker.md](.claude/skills/hragent-docker.md) | Docker Compose 服务管理（启动/重建/日志/健康检查） |
| `redis-cache-facade` | [.claude/skills/redis-cache-facade.md](.claude/skills/redis-cache-facade.md) | Redis 缓存门面模式（通用 Python 可复用模板） |
| `hragent-build-verify` | [.claude/skills/hragent-build-verify.md](.claude/skills/hragent-build-verify.md) | 构建与验证标准工作流 |
| `fastapi-pydantic-settings` | [.claude/skills/fastapi-pydantic-settings.md](.claude/skills/fastapi-pydantic-settings.md) | FastAPI 配置管理模式（通用跨项目模板） |
| `locust-loadtest` | [.claude/skills/locust-loadtest.md](.claude/skills/locust-loadtest.md) | Locust 压测框架（冒烟测试+并发压测） |
| `hragent-api-pattern` | [.claude/skills/hragent-api-pattern.md](.claude/skills/hragent-api-pattern.md) | API 服务开发模式（新增接口/业务域的开发规范） |
| `hragent-token-concurrency` | [.agents/skills/hragent-token-concurrency/SKILL.md](.agents/skills/hragent-token-concurrency/SKILL.md) | 外部模型 API 的 Token 降耗、并发治理与分阶段验收 |

另有业务域 Skill：[HRagent-05_standard_SKILL.md](HRagent-05_standard_SKILL.md)（OCEAN + MVPI 动态情绪预演完整规范）。


## Token 降耗与高并发专项

涉及 Prompt、LLM 调用次数、对话上下文、模型并发、外部 API 限流、singleflight、重试、Token 监控或 Locust 完整流程压测时，必须使用 `hragent-token-concurrency` Skill，并遵守以下规则：

1. 以 `specs/token-concurrency-optimization/README.md` 的状态表为唯一阶段入口，严格按 `01` 到 `07` 顺序实施。
2. 一次只实施用户明确授权的一个阶段；当前阶段验收未通过时，不得进入下一阶段或标记完成。
3. 本专项仅使用 `main` 基线支持的外部模型 API；不得合并或移植 `ollama` 分支，不得操作 Ollama、GPU 或模型卷。
4. 完整 15 轮流程的输入 Token 目标为相对阶段 01 基线至少降低 50%；50 用户验收要求至少 49 条完整流程结束且总失败率低于 1%。
5. 保持成功响应、SSE 事件顺序、业务 Schema 和六步流程兼容；不得缓存完整 AI 员工回复。
6. 阶段执行不得记录 Prompt、完整模型回复、员工正文或真实凭据；测试只能使用隔离的合成资料和专用账号。
7. 模型、服务地址、数据库迁移、鉴权、公开输出结构、Docker 或外部基础设施变更仍按高风险操作重新确认。


## 项目说明

本项目是 HRagent-05，面向博世内部 HR/HRBP 的绩效反馈准备、谈前指导、对话预演和复盘报告工作台。

主要技术栈和目录：

- 前端：React + TypeScript + Vite，主要目录为 `frontend/`，生产环境由 nginx 提供静态资源和反向代理。
- 后端：FastAPI / Uvicorn + Python 3.11 + Pydantic + LangGraph/LangChain，主要目录为 `backend/`。
- 数据服务：PostgreSQL + pgvector、Redis、MinerU 文档解析服务。
- 业务数据：默认挂载在 `data/`，Redis 持久化数据位于 `data/redis/`。

修改前必须先阅读相关文件和调用链，保持现有业务逻辑、接口契约和用户流程稳定。

## 当前服务与端口

仅使用 HRagent-05 对应容器和服务，不要操作 HRagent-06 或其他用户的容器。

Docker Compose 服务：

- `frontend`：HTTP `8080`，HTTPS `8443`
- `backend`：`8111`
- `postgres`：`5432`
- `redis`：宿主机 `6381` 映射容器 `6379`
- `mineru`：宿主机 `18000` 映射容器 `8000`

后端容器内 Redis 地址为 `redis://redis:6379/0`。`data/redis/` 必须保留在 `.dockerignore` 中，避免 Docker build context 因 Redis 持久化目录权限失败。

## 常用命令

优先使用以下命令检查和启动 05 服务：

```bash
# 查看当前 05 服务状态
docker compose ps

# 启动基础服务和前后端
docker compose up -d postgres redis backend frontend

# 只重建后端
docker compose build backend
docker compose up -d backend

# 只重建前端
docker compose build frontend
docker compose up -d frontend

# 查看日志
docker compose logs --tail=120 backend
docker compose logs --tail=120 frontend

# 健康检查
curl -fsS http://localhost:8111/api/v1/health
curl -k -fsS https://localhost:8443/api/v1/health

# Redis 检查
docker compose exec -T redis redis-cli ping
```

`docker compose up --build` 会触发多服务重建，只有在明确需要整体重建时再使用。涉及网络、Docker、远端 API 或容器状态的命令，执行前说明目的和影响。

## 修改边界

1. 只处理当前需求，不顺手重构无关代码。
2. 不修改 HRagent-06、其他仓库或其他用户容器。
3. 不删除 `data/` 中的上传文件、解析结果、Redis/PostgreSQL 持久化数据，除非用户明确要求。
4. 不输出、不提交、不复制 `.env` 中的密钥、Token、账号密码或真实凭证。
5. 可以更新`.env `,`.env.example` 的非敏感配置说明，但不要把真实 key 写入示例文件。
6. 不随意升级依赖、改 Docker 端口、改服务名、改数据库 schema 或改 API 返回结构。
7. 发现需求外的问题时先记录风险或建议，不直接扩大修改范围。

## 后端规则

1. 修改接口前先确认请求参数、响应结构、错误处理和前端调用点。
2. 保持已有 API 响应格式稳定，尤其是 workflow、guidance、rehearsal、ASR/TTS、document parsing 相关接口。
3. Redis 缓存必须通过 `backend/services/cache_service.py` 接入；缓存失败只能降级为原逻辑，不能阻断业务流程。
4. 当前允许缓存：TTS 音频、文档解析结果、谈前指导结果、对话预演的中间情绪信号。
5. 对话预演不缓存完整 AI 员工回复，避免把动态人格化对话固化。
6. TTS 缓存 key 必须包含文本、模型、音色、语速、格式等会影响音频结果的字段。
7. 文档解析缓存 key 必须包含文件内容 hash，以及解析器、MinerU 配置、解析策略等关键参数。
8. Guidance 缓存 key 必须覆盖员工档案、沟通意图、Persona、难度、模型、知识库版本和相关上下文。
9. ASR/TTS 的 API key 只能在后端或服务端配置中使用，严禁暴露到前端代码和浏览器环境。
10. 涉及数据库迁移、鉴权、全局中间件、模型参数和提示词输出结构时，必须说明风险和验证方式。

## 前端规则

1. UI 保持博世风格：克制、清晰、企业级、低装饰度，优先信息密度和可扫描性。
2. 优先复用已有组件、样式变量和页面结构，不新增 UI 库，除非用户明确要求。
3. 不改变已有业务流程和按钮语义，特别是员工信息、沟通意图、Persona、谈前指导、预演、复盘六步流程。
4. 左侧步骤栏、Bosch logo、预演输入区、报告区域等已做过定制，改动时保持现有交互预期。
5. ASR 输入保持实时语音转文字体验；用户确认或发送前，不要自动把识别文本提交为 HRBP 回复。
6. TTS 输出按当前需求可一次性播放完整语句，避免按标点切割导致语义断裂。
7. 修改页面布局后，检查桌面宽屏、`8080` HTTP 和 `8443` HTTPS 入口是否仍可访问。

## 构建与验证

后端改动后优先执行：

```bash
docker compose build backend
docker compose up -d backend
curl -fsS http://localhost:8111/api/v1/health
```

前端改动后优先执行：

```bash
docker compose build frontend
docker compose up -d frontend
curl -k -fsS https://localhost:8443/api/v1/health
```

Redis 相关改动后至少检查：

```bash
docker compose exec -T redis redis-cli ping
```

如果无法在当前环境完成构建、启动或接口测试，最终回复必须明确说明未验证项和原因。

## 安全要求

1. 不在回复、日志摘录或文档中暴露真实密钥。
2. 不执行 `git reset --hard`、`rm -rf`、`docker compose down -v`、清空数据目录、删除卷等破坏性操作，除非用户明确要求并确认影响。
3. 不修改生产或共享环境配置，除非当前任务明确要求。
4. 不把 ASR、TTS、LLM、Embedding、Rerank 等服务 key 写入前端、截图或可公开文件。
5. 处理 HTTPS、麦克风、WebSocket、nginx 代理问题时，优先定位协议、证书、安全上下文和代理转发配置，不绕过安全限制。

## 输出要求

完成任务后用简洁中文说明：

- 修改了哪些文件；
- 每个文件的关键改动；
- 已执行的验证命令和结果；
- 未验证项、残余风险或需要用户确认的事项。

如果用户要求代码审查，先列问题和风险，再给简短总结。若没有发现问题，也要说明测试覆盖或剩余风险。

## 高风险操作

以下操作必须先说明影响并等待用户确认：

1. 删除文件、清空目录、删除 Docker volume 或数据库数据；
2. 批量重构、跨模块迁移或大范围格式化；
3. 安装、删除或升级依赖；
4. 修改 Docker Compose 服务名、端口、volume、网络或 GPU/MinerU 配置；
5. 修改数据库 schema、迁移文件、鉴权、权限、Token、密钥处理逻辑；
6. 改变缓存 key、TTL、失效策略或缓存范围；
7. 改变 ASR/TTS/LLM 模型、服务地址、请求协议或输出结构。
