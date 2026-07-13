## 已接入的缓存：
### 1.TTS 缓存
文件：[tts_service.py](/home/aah5sgh/HRagent-05/backend/services/tts_service.py)
key 基于 model + voice + speed + format + text
命中后直接返回 Redis 里的音频 bytes，不再请求 TTS 接口
默认 TTL：7 天

### 2.文档解析缓存
文件：[document_pipeline.py](/home/aah5sgh/HRagent-05/backend/services/document_pipeline.py)
文件按 sha256(file_bytes) + MinerU 配置 + KB 版本 缓存
文本按 sha256(text) 缓存
命中后会替换为当前新的 document_id，不污染当前上传记录
默认 TTL：30 天

### 3.Guidance 缓存
文件：[guidance_service.py](/home/aah5sgh/HRagent-05/backend/services/guidance_service.py)
key 基于员工 profile、意图、Persona、难度、run_mode、检索 chunks、guidance model、KB 版本
支持普通生成和流式生成
命中后仍会保存当前 session 的 guidance 状态
默认 TTL：6 小时

### 4.Rehearsal 中间结果缓存
文件：[nodes.py](/home/aah5sgh/HRagent-05/backend/workflows/nodes.py)
只缓存情绪分析 EmotionSignal
不缓存完整员工回复，避免对话不自然
默认 TTL：1 小时

### 5.新增通用缓存层：
[cache_service.py](/home/aah5sgh/HRagent-05/backend/services/cache_service.py)
Redis 异常不会打断业务，只会退化为原来的无缓存逻辑
配置/依赖：
[settings.py](/home/aah5sgh/HRagent-05/backend/config/settings.py)
[.env.example](/home/aah5sgh/HRagent-05/backend/config/.env.example)
[requirements.txt](/home/aah5sgh/HRagent-05/backend/requirements.txt)：新增 redis>=5.0

## 已验证：
docker compose build backend 成功
python -m compileall backend 成功
Redis 基础读写冒烟成功：{'ok': True}
已重启 05 backend
后端健康检查正常
前端 HTTPS 代理健康检查正常
Redis / backend / frontend / postgres 均运行正常
缓存会在后续实际调用 TTS、上传文档、生成 Guidance、进行预演情绪分析时自动写入。

## 触发预演情绪分析缓存
员工信息 -> 沟通意图 -> Persona -> 谈前指导 -> 预演