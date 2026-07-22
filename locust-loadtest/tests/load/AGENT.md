## 一定要遵守
DO NOT send optional commentary

启动命令按照一下进行启动，不需要修改：
# Inject the test account from the shell or a secret manager.
: "${HRAGENT_EMAIL:?Set HRAGENT_EMAIL before running Locust}"
export HRAGENT_EMAIL
# Inject this value from the shell or a secret manager; never store it here.
: "${HRAGENT_PASSWORD:?Set HRAGENT_PASSWORD before running Locust}"
export HRAGENT_PASSWORD
export HRAGENT_AUTH_ENABLED=true

locust -f locust-loadtest/tests/load/hragent_locustfile.py \
  -H http://localhost:8111 \
  --web-host 0.0.0.0 \
  --web-port 8099

## 修改边界

1. 只处理当前需求，不顺手重构无关代码。
2. 不修改 HRagent-06、其他仓库或其他用户容器。
3. 不删除 `data/` 中的上传文件、解析结果、Redis/PostgreSQL 持久化数据，除非用户明确要求。
4. 不输出、不提交、不复制 `.env` 中的密钥、Token、账号密码或真实凭证。
5. 可以更新`.env `,`.env.example` 的非敏感配置说明，但不要把真实 key 写入示例文件。
6. 不随意升级依赖、改 Docker 端口、改服务名、改数据库 schema 或改 API 返回结构。
7. 发现需求外的问题时先记录风险或建议，不直接扩大修改范围。
