# 可执行工具箱

所有脚本仅使用 Python 标准库。优先直接运行脚本，不要把脚本源码全文加载进上下文。

## 安全约束

- 仅处理合成、脱敏或聚合数据。
- 不把 Prompt、完整回复、邮箱、会话标识或凭据写入输入文件。
- 使用 `user_ref` 等不可逆伪匿名引用，不使用真实用户标识。
- 临时测试文件写入系统临时目录，不提交到仓库。
- Tokenizer 估算必须明确标记为估算，不能冒充 Provider 用量。

## 1. 聚合用量和费用

使用 [scripts/aggregate_usage.py](../scripts/aggregate_usage.py) 聚合 JSONL：

```bash
python scripts/aggregate_usage.py events.jsonl \
  --pricing pricing.json \
  --group-by provider model \
  --output summary.json
```

JSONL 支持两种记录。

完整流程记录：

```json
{"record_type":"workflow","workflow_id":"synthetic-001","status":"completed","latency_ms":1200}
```

用量记录：

```json
{"record_type":"usage","workflow_id":"synthetic-001","task":"answer","provider":"vendor","model":"model-a","status":"success","usage_source":"provider","input_tokens":100,"cached_input_tokens":20,"output_tokens":30,"reasoning_tokens":0,"calls":1,"retries":0,"other_cost":0}
```

约定：

- `input_tokens` 只记录非缓存输入，缓存部分单独放入 `cached_input_tokens`。
- 每个完整流程只写一条 `workflow` 记录。
- `usage_source` 使用 `provider`、`estimated` 或 `unavailable`。
- 可按 `provider`、`model`、`task`、`feature`、`route`、`operation`、`usage_source`、`status`、`user_ref` 或 `tenant_ref` 分组。
- 缺少价格的用量不会按零处理，`total_cost` 将为 `null`。

价格文件：

```json
{
  "currency": "CNY",
  "effective_date": "2026-01-01",
  "unit_tokens": 1000000,
  "models": {
    "vendor/model-a": {
      "input": 1.0,
      "cached_input": 0.2,
      "output": 4.0,
      "reasoning": 4.0,
      "per_request": 0.0
    }
  }
}
```

价格必须来自目标环境的有效来源，不复用示例数字。

## 2. 对比基线与候选结果

使用 [scripts/compare_runs.py](../scripts/compare_runs.py) 对比两个聚合结果：

```bash
python scripts/compare_runs.py baseline.json candidate.json \
  --min-baseline-workflows 10 \
  --min-candidate-workflows 10 \
  --min-token-reduction-pct 20 \
  --min-cost-reduction-pct 10 \
  --max-failure-rate-pct 1 \
  --max-p95-regression-pct 10 \
  --max-retry-rate-pct 2 \
  --require-all-priced
```

退出码：

- `0`：全部门禁通过。
- `1`：输入、Schema 或执行错误。
- `2`：至少一个质量门禁未通过。

只有设置相同价格元数据后，费用降低门禁才可通过。

## 3. 审计合成请求载荷

使用 [scripts/audit_payload.py](../scripts/audit_payload.py) 检查重复文本、最大字段和字符预算：

```bash
python scripts/audit_payload.py synthetic-payload.json \
  --confirm-synthetic \
  --min-duplicate-chars 20 \
  --max-chars 12000
```

脚本只输出路径、长度和内容指纹，不输出文本值。`--chars-per-token` 仅用于用户提供的粗略估算；正式验收应使用 Provider 返回或目标模型 Tokenizer。

## 推荐组合

1. 用 `audit_payload.py` 定位重复上下文和超大字段。
2. 用 `aggregate_usage.py` 生成优化前后同口径汇总。
3. 用 `compare_runs.py` 执行非零流程、Token、费用、延迟和失败率门禁。
4. 将汇总结果与独立的质量、Schema、安全和流式测试一起判断，不能只凭脚本结果发布。
