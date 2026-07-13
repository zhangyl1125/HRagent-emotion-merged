# LangSmith 使用说明

## 当前接入状态

本项目已经通过环境变量接入 LangSmith tracing。后端容器启动时会从 `backend/config/.env` 读取配置，LangChain 相关调用在 tracing 打开后会自动上报 trace。

已配置的关键变量：

```bash
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=<已写入本地 .env，文档中不展示>
LANGSMITH_PROJECT=hragent-05
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
```

同时保留兼容变量：

```bash
LANGCHAIN_TRACING_V2=true
LANGCHAIN_PROJECT=hragent-05
```

## 如何生效

修改 `.env` 后需要重启后端容器：

```bash
docker compose up -d backend
```

确认容器中已经读取配置，但不要打印真实 key：

```bash
docker compose exec -T backend python -c "import os; print(os.getenv('LANGSMITH_TRACING'), bool(os.getenv('LANGSMITH_API_KEY')), os.getenv('LANGSMITH_PROJECT'))"
```

预期输出类似：

```text
true True hragent-05
```

## 如何查看 Trace

1. 打开 LangSmith 控制台：`https://smith.langchain.com/`
2. 进入项目 `hragent-05`。
3. 在前端触发一次会调用 LangChain 的流程，例如：
   - 上传或粘贴员工信息后抽取员工档案；
   - 生成谈前指导；
   - 对话预演中生成员工回复；
   - 生成复盘报告。
4. 刷新 LangSmith 项目页面，查看对应 trace、LLM run、耗时、输入输出和错误信息。

## 常用排查

### 1. LangSmith 页面没有 Trace

检查后端容器是否已经重启并读取变量：

```bash
docker compose exec -T backend python -c "import os; print(os.getenv('LANGSMITH_TRACING'), bool(os.getenv('LANGSMITH_API_KEY')), os.getenv('LANGSMITH_PROJECT'))"
```

如果 `LANGSMITH_TRACING` 不是 `true`，说明容器还没有拿到最新 `.env`，重启 backend。

### 2. 鉴权失败

确认 `LANGSMITH_API_KEY` 是 LangSmith API Key，并且 key 所属 workspace 有权限写入项目。

如果账号不是默认 US 区域，需要调整：

```bash
LANGSMITH_ENDPOINT=<对应区域的 LangSmith API 地址>
```

### 3. 只想临时关闭 tracing

把本地 `.env` 中的：

```bash
LANGSMITH_TRACING=false
LANGCHAIN_TRACING_V2=false
```

然后重启 backend。

## 使用建议

- 开发调试时开启 tracing，方便定位模型调用慢、结构化输出失败、RAG 上下文不足等问题。
- 演示或压测时可单独设置 `LANGSMITH_PROJECT`，例如 `hragent-05-demo`，避免 trace 混在一起。
- 不要把 `LANGSMITH_API_KEY` 写入 README、截图、前端代码或提交记录。
- 如果要给单次调用添加标签或元数据，可在 LangChain runnable 调用时传入 `tags`、`metadata` 或 `run_name`。

## Context7 配置说明

当前环境没有可直接调用的 Context7 MCP 工具，也没有可安装的 Context7 插件。已在 Claude 配置中加入 remote MCP server：

```json
{
  "mcpServers": {
    "context7": {
      "type": "http",
      "url": "https://mcp.context7.com/mcp"
    }
  }
}
```

Context7 需要重启 Claude/Codex 后由宿主程序加载。加载成功后，可在提示词中使用：

```text
use context7
```

或指定库 ID：

```text
use library /langchain-ai/langsmith for LangSmith tracing docs
```

## 参考来源

- Context7 官方仓库：`https://github.com/upstash/context7`
- LangSmith tracing 文档：`https://docs.langchain.com/langsmith/trace-with-langchain`
- LangSmith Observability 文档：`https://docs.langchain.com/langsmith/observability`
