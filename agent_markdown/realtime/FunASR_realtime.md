# HRagent-05：本地 Docker 实时语音输入转文字改造任务文档

## 0. 任务目标

将当前 HRagent-05 项目的语音输入能力改造成：

```text
浏览器麦克风输入
  ↓
前端采集 16k PCM 音频流
  ↓
后端 WebSocket：/asr/realtime
  ↓
本地 Docker 容器 FunASR 实时识别服务
  ↓
实时返回 partial / final 文本
  ↓
前端输入框实时显示文字
```

本阶段只做 **语音输入实时转文字 ASR**，不做 TTS，不做文字转语音输出。

---

## 1. 强制约束

AI 代码编辑时必须遵守以下约束：

1. **不再使用 Qwen Realtime API。**
   - 当前 Realtime API 无法使用，所以实时语音识别必须改成本地 Docker 服务。

2. **不新建新的 `docker-compose` 文件。**
   - 不允许新增 `docker-compose.funasr.yml`、`docker-compose.asr.yml`、`compose.asr.yml` 等文件。
   - FunASR 容器必须直接加入项目现有的 `docker-compose.yml`。

3. **不使用长期独立 `docker run` 方式部署。**
   - 可以在文档中保留测试命令，但正式实现必须通过现有 `docker-compose.yml` 编排。

4. **尽量保留现有前端实时录音逻辑。**
   - 当前 `frontend/src/hooks/useRealtimeAsr.ts` 已经会采集麦克风，并将 16k PCM bytes 发送到 `/asr/realtime`。
   - 不要重写前端录音模块。
   - 如无必要，不改前端。

5. **后端接口路径保持不变。**
   - 前端仍然访问：

```text
/asr/realtime
```

6. **只替换后端 ASR Provider。**
   - 原来的 `QwenRealtimeAsrProxy` 保留。
   - 新增 `FunAsrRealtimeAsrProxy`。
   - 通过环境变量 `ASR_PROVIDER=funasr` 切换。

---

## 2. 推荐技术方案

使用 FunASR Runtime Online Docker 服务。

推荐镜像：

```text
registry.cn-hangzhou.aliyuncs.com/funasr_repo/funasr:funasr-runtime-sdk-online-cpu-0.1.13
```

推荐模式：

```text
mode = 2pass
```

原因：

```text
2pass = 实时流式识别 + 句尾离线模型纠错
```

也就是说：

```text
2pass-online  ：说话过程中实时出字
2pass-offline ：一句话结束后输出修正后的结果
```

---

## 3. 需要修改的文件清单

必须修改：

```text
docker-compose.yml
backend/config/settings.py
backend/config/.env.example
backend/services/asr_service.py
backend/api/routes/asr.py
```

运行环境需要修改：

```text
backend/config/.env
```

不建议修改：

```text
frontend/src/hooks/useRealtimeAsr.ts
```

只有在发现 final 文本覆盖、多句丢失时，再小范围修正前端合并逻辑。

---

## 4. 修改 `docker-compose.yml`

### 4.1 在现有 `services:` 下新增 `funasr` 服务

直接在当前 `docker-compose.yml` 的 `services:` 下新增以下服务，建议放在 `mineru` 与 `backend` 之间：

```yaml
  funasr:
    image: registry.cn-hangzhou.aliyuncs.com/funasr_repo/funasr:funasr-runtime-sdk-online-cpu-0.1.13
    restart: unless-stopped
    privileged: true
    working_dir: /workspace/FunASR/runtime
    ports:
      - "10096:10095"
    volumes:
      - ./data/funasr/models:/workspace/models
    extra_hosts:
      - "host.docker.internal:host-gateway"
    environment:
      HTTP_PROXY: http://host.docker.internal:3128
      HTTPS_PROXY: http://host.docker.internal:3128
      http_proxy: http://host.docker.internal:3128
      https_proxy: http://host.docker.internal:3128
      NO_PROXY: localhost,127.0.0.1,::1,backend,frontend,postgres,redis,mineru,funasr
      no_proxy: localhost,127.0.0.1,::1,backend,frontend,postgres,redis,mineru,funasr
    command: >
      bash -lc "
      nohup bash run_server_2pass.sh
      --download-model-dir /workspace/models
      --vad-dir damo/speech_fsmn_vad_zh-cn-16k-common-onnx
      --model-dir damo/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-onnx
      --online-model-dir damo/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online-onnx
      --punc-dir damo/punc_ct-transformer_zh-cn-common-vad_realtime-vocab272727-onnx
      --lm-dir damo/speech_ngram_lm_zh-cn-ai-wesp-fst
      --itn-dir thuduj12/fst_itn_zh
      --certfile 0
      > /workspace/funasr.log 2>&1 &
      tail -f /workspace/funasr.log
      "
```

### 4.2 修改 backend 的 `depends_on`

找到当前 `backend` 服务中的：

```yaml
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
```

改成：

```yaml
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
      funasr:
        condition: service_started
```

说明：

- FunASR 首次启动会下载模型，耗时可能较长。
- 不建议强依赖 `service_healthy`，否则模型下载期间可能导致 backend 等待或启动失败。
- 只要求容器启动即可，用户实际点击麦克风时再连接 `ws://funasr:10095`。

### 4.3 修改 backend 的 `NO_PROXY`

在 `backend.build.args.NO_PROXY` 和 `backend.environment.NO_PROXY / no_proxy` 里加入：

```text
funasr
```

修改后类似：

```yaml
NO_PROXY: localhost,127.0.0.1,::1,backend,frontend,postgres,redis,mineru,funasr
no_proxy: localhost,127.0.0.1,::1,backend,frontend,postgres,redis,mineru,funasr
```

这样 backend 访问 `ws://funasr:10095` 时不会走公司代理。

---

## 5. 修改 `backend/config/settings.py`

### 5.1 修改 ASR Provider 类型

找到：

```python
asr_provider: Literal["qwen"] = "qwen"
```

改成：

```python
asr_provider: Literal["qwen", "funasr"] = "qwen"
```

注意：默认值可以保留 `qwen`，真正切换由 `.env` 中的 `ASR_PROVIDER=funasr` 控制。

### 5.2 增加 FunASR 配置项

在 ASR 配置区域中加入：

```python
# FunASR local realtime service
funasr_ws_url: str = "ws://funasr:10095"
funasr_mode: Literal["online", "2pass"] = "2pass"
funasr_chunk_size: list[int] = [5, 10, 5]
funasr_itn: bool = True
funasr_hotwords: str = ""
```

建议放在：

```python
asr_max_session_seconds: int = 300
```

后面。

---

## 6. 修改 `backend/config/.env.example`

找到 ASR 配置区域，将默认 ASR Provider 改成 FunASR：

```env
# =========================
# ASR / Speech-to-Text
# =========================
ASR_ENABLED=true
ASR_PROVIDER=funasr
ASR_MODEL=funasr-paraformer-2pass
ASR_API_KEY=
ASR_WS_URL=
ASR_HTTP_URL=https://aigc.bosch.com.cn/llmservice/api/v1/audio/transcriptions
ASR_HTTP_MODEL=qwen3-asr-flash
ASR_LANGUAGE=zh
ASR_SAMPLE_RATE=16000
ASR_INPUT_AUDIO_FORMAT=pcm
ASR_ENABLE_SERVER_VAD=true
ASR_VAD_THRESHOLD=0.0
ASR_VAD_SILENCE_DURATION_MS=400
ASR_CONNECT_TIMEOUT_SECONDS=15
ASR_SESSION_TIMEOUT_SECONDS=120
ASR_MAX_SESSION_SECONDS=300

# FunASR local realtime WebSocket service
FUNASR_WS_URL=ws://funasr:10095
FUNASR_MODE=2pass
FUNASR_CHUNK_SIZE=[5,10,5]
FUNASR_ITN=true
FUNASR_HOTWORDS=
```

说明：

- `ASR_API_KEY` 对 FunASR 实时识别不需要。
- `ASR_WS_URL` 对 FunASR 实时识别不需要。
- `ASR_HTTP_URL` 可以保留给原来的 HTTP 录音文件 fallback 使用。
- 本阶段主链路只走 `FUNASR_WS_URL=ws://funasr:10095`。

---

## 7. 修改运行环境 `backend/config/.env`

如果项目当前没有 `backend/config/.env`，先复制：

```bash
cp backend/config/.env.example backend/config/.env
```

然后确保其中包含：

```env
ASR_ENABLED=true
ASR_PROVIDER=funasr
ASR_MODEL=funasr-paraformer-2pass
ASR_SAMPLE_RATE=16000
ASR_INPUT_AUDIO_FORMAT=pcm
ASR_MAX_SESSION_SECONDS=300

FUNASR_WS_URL=ws://funasr:10095
FUNASR_MODE=2pass
FUNASR_CHUNK_SIZE=[5,10,5]
FUNASR_ITN=true
FUNASR_HOTWORDS=
```

---

## 8. 修改 `backend/services/asr_service.py`

### 8.1 保留原有 Qwen 类

不要删除：

```python
class QwenRealtimeAsrProxy:
    ...
```

### 8.2 新增 FunASR 代理类

在 `QwenRealtimeAsrProxy` 后面新增以下类：

```python
class FunAsrRealtimeAsrProxy:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._funasr_ws: Any | None = None
        self._started_at = time.monotonic()
        self._closed = False
        self._wav_name = f"hragent_{int(time.time() * 1000)}"
        self._committed_text = ""
        self._last_preview = ""

    def validate(self) -> None:
        if not self.settings.asr_enabled:
            raise AsrConfigurationError("ASR is disabled")
        if not self.settings.funasr_ws_url:
            raise AsrConfigurationError("FUNASR_WS_URL is empty")
        ws_url = self.settings.funasr_ws_url.strip().lower()
        if not ws_url.startswith(("ws://", "wss://")):
            raise AsrConfigurationError("FUNASR_WS_URL 必须是 ws:// 或 wss:// 开头。")

    async def connect(self) -> None:
        self.validate()
        self._funasr_ws = await websockets.connect(
            self.settings.funasr_ws_url,
            open_timeout=self.settings.asr_connect_timeout_seconds,
            ping_interval=20,
            ping_timeout=20,
            max_size=8 * 1024 * 1024,
        )

        init_payload: dict[str, Any] = {
            "mode": self.settings.funasr_mode,
            "wav_name": self._wav_name,
            "is_speaking": True,
            "wav_format": "pcm",
            "audio_fs": self.settings.asr_sample_rate,
            "chunk_size": self.settings.funasr_chunk_size,
            "itn": self.settings.funasr_itn,
        }

        hotwords = str(self.settings.funasr_hotwords or "").strip()
        if hotwords:
            init_payload["hotwords"] = hotwords

        await self._funasr_ws.send(json.dumps(init_payload, ensure_ascii=False))

    async def append_audio(self, pcm_bytes: bytes) -> None:
        if self._closed:
            return
        if time.monotonic() - self._started_at > self.settings.asr_max_session_seconds:
            raise TimeoutError("ASR session exceeded maximum duration")
        if not pcm_bytes:
            return
        if not self._funasr_ws:
            raise RuntimeError("FunASR websocket is not connected")
        await self._funasr_ws.send(pcm_bytes)

    async def finish(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._funasr_ws:
            try:
                await self._funasr_ws.send(json.dumps({"is_speaking": False}, ensure_ascii=False))
            except Exception:
                pass

    async def close(self) -> None:
        self._closed = True
        if self._funasr_ws:
            await self._funasr_ws.close(code=1000, reason="client closed")

    async def receive_loop(self, send_frontend: SendFrontend) -> None:
        if not self._funasr_ws:
            raise RuntimeError("FunASR websocket is not connected")

        try:
            async for raw in self._funasr_ws:
                if isinstance(raw, bytes):
                    continue
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                normalized = self.normalize_funasr_event(data)
                if normalized:
                    await send_frontend(normalized)

        except ConnectionClosed:
            return

    @staticmethod
    def _concat_text(prefix: str, suffix: str) -> str:
        prefix = prefix.strip()
        suffix = suffix.strip()
        if not prefix:
            return suffix
        if not suffix:
            return prefix
        if suffix == prefix or prefix.endswith(suffix):
            return prefix
        if suffix.startswith(prefix):
            return suffix

        max_overlap = min(len(prefix), len(suffix), 30)
        for size in range(max_overlap, 0, -1):
            if prefix.endswith(suffix[:size]):
                return f"{prefix}{suffix[size:]}"

        if prefix[-1:].isascii() and prefix[-1:].isalnum() and suffix[:1].isascii() and suffix[:1].isalnum():
            return f"{prefix} {suffix}"
        return f"{prefix}{suffix}"

    def normalize_funasr_event(self, data: dict[str, Any]) -> dict[str, Any] | None:
        text = str(data.get("text") or "").strip()
        if not text:
            return None

        mode = str(data.get("mode") or "")
        is_final = bool(data.get("is_final"))

        is_offline_result = mode in {"offline", "2pass-offline"}
        is_online_result = mode in {"online", "2pass-online"}

        if is_offline_result or (is_final and not is_online_result):
            self._committed_text = self._concat_text(self._committed_text, text)
            self._last_preview = self._committed_text
            return {
                "type": "final",
                "transcript": self._committed_text,
                "emotion": None,
            }

        preview = self._concat_text(self._committed_text, text)
        if preview == self._last_preview:
            return None
        self._last_preview = preview
        return {
            "type": "partial",
            "text": text,
            "preview": preview,
            "emotion": None,
        }
```

### 8.3 注意事项

1. FunASR 的音频发送方式是 **直接发送 PCM bytes**，不是 base64。
2. 结束时发送：

```json
{"is_speaking": false}
```

3. 首次连接必须发送初始化 JSON：

```json
{
  "mode": "2pass",
  "wav_name": "hragent_xxx",
  "is_speaking": true,
  "wav_format": "pcm",
  "audio_fs": 16000,
  "chunk_size": [5, 10, 5],
  "itn": true
}
```

4. 后端返回给前端的事件格式必须继续保持：

```json
{"type":"partial","preview":"..."}
```

或者：

```json
{"type":"final","transcript":"..."}
```

这样可以复用现有 `useRealtimeAsr.ts`。

---

## 9. 修改 `backend/api/routes/asr.py`

### 9.1 修改 import

找到：

```python
from backend.services.asr_service import AsrConfigurationError, QwenRealtimeAsrProxy
```

改成：

```python
from backend.services.asr_service import (
    AsrConfigurationError,
    FunAsrRealtimeAsrProxy,
    QwenRealtimeAsrProxy,
)
```

### 9.2 修改 `/asr/realtime` 中的 proxy 创建逻辑

找到：

```python
proxy = QwenRealtimeAsrProxy(settings)
```

改成：

```python
if settings.asr_provider == "funasr":
    proxy = FunAsrRealtimeAsrProxy(settings)
else:
    proxy = QwenRealtimeAsrProxy(settings)
```

其他逻辑保持不变。

---

## 10. 不建议修改前端，但需要确认现有前端行为

当前前端文件：

```text
frontend/src/hooks/useRealtimeAsr.ts
```

已经具备以下能力：

1. 通过浏览器麦克风采集音频。
2. 将音频重采样为 16k。
3. 转成 PCM16 little-endian。
4. 通过 WebSocket 发送到：

```text
/asr/realtime
```

5. 接收：

```json
{"type":"partial","preview":"..."}
```

和：

```json
{"type":"final","transcript":"..."}
```

因此前端可以先不改。

如果测试时发现多句话 final 文本覆盖上一句，再修改 `emitTranscript` 的 final 合并逻辑，但第一轮不要主动重写。

---

## 11. 启动与验证命令

### 11.1 校验 compose 文件

```bash
docker compose config
```

必须无 YAML 语法错误。

### 11.2 拉取并启动 FunASR

```bash
docker compose pull funasr
docker compose up -d funasr
```

查看日志：

```bash
docker compose logs -f funasr
```

首次启动会下载模型，时间可能较长。

### 11.3 启动后端和前端

```bash
docker compose up -d --build backend frontend
```

### 11.4 检查 backend 是否能访问 FunASR 端口

```bash
docker compose exec backend python - <<'PY'
import socket
s = socket.create_connection(("funasr", 10095), timeout=5)
print("FunASR port ok")
s.close()
PY
```

### 11.5 检查后端配置是否读取成功

```bash
docker compose exec backend python - <<'PY'
from backend.config.settings import get_settings
s = get_settings()
print("ASR_ENABLED=", s.asr_enabled)
print("ASR_PROVIDER=", s.asr_provider)
print("FUNASR_WS_URL=", s.funasr_ws_url)
print("FUNASR_MODE=", s.funasr_mode)
print("FUNASR_CHUNK_SIZE=", s.funasr_chunk_size)
PY
```

期望输出：

```text
ASR_ENABLED= True
ASR_PROVIDER= funasr
FUNASR_WS_URL= ws://funasr:10095
FUNASR_MODE= 2pass
FUNASR_CHUNK_SIZE= [5, 10, 5]
```

### 11.6 浏览器测试

访问：

```text
https://服务器IP:8443
```

进入对话预演页面，点击语音输入按钮。

预期效果：

```text
开始说话后：输入框出现实时文字
停顿后：文字被 FunASR 2pass-offline 修正
点击停止后：最终文本保留在输入框中
```

---

## 12. 验收标准

完成后必须满足：

1. `docker-compose.yml` 中出现 `funasr` 服务。
2. 没有新增任何新的 compose yaml 文件。
3. `docker compose config` 通过。
4. `docker compose ps` 能看到 `funasr`、`backend`、`frontend`。
5. 后端 `.env` 中 `ASR_PROVIDER=funasr`。
6. 后端 `/asr/realtime` 不再强制要求 `ASR_API_KEY`。
7. 前端麦克风输入后，可以实时显示识别文字。
8. 停顿后能收到更稳定的修正文本。
9. 原来的 Qwen ASR 代码没有被删除，后续仍可通过 `ASR_PROVIDER=qwen` 回退。

---

## 13. 禁止事项

AI 代码编辑时禁止：

1. 禁止新建 `docker-compose.funasr.yml`。
2. 禁止删除原有 `docker-compose.yml` 中的 `postgres / redis / mineru / backend / frontend`。
3. 禁止删除 `QwenRealtimeAsrProxy`。
4. 禁止大改前端录音逻辑。
5. 禁止把 FunASR 地址写成宿主机地址 `localhost:10096` 给 backend 使用。
   - backend 容器内部必须使用：

```text
ws://funasr:10095
```

6. 禁止让 backend 访问 FunASR 时走 HTTP 代理。
   - 必须把 `funasr` 加入 `NO_PROXY / no_proxy`。

---

## 14. 常见问题处理

### 14.1 FunASR 日志一直在下载模型

首次启动正常，等待下载完成。

模型会缓存到：

```text
./data/funasr/models
```

后续重启不需要重复下载。

### 14.2 backend 连接 FunASR 失败

先检查容器：

```bash
docker compose ps
```

再检查端口：

```bash
docker compose exec backend python - <<'PY'
import socket
s = socket.create_connection(("funasr", 10095), timeout=5)
print("ok")
s.close()
PY
```

如果失败，检查：

```bash
docker compose logs -f funasr
```

### 14.3 浏览器无法打开麦克风

必须使用：

```text
https://服务器IP:8443
```

不要用普通 HTTP 地址。

浏览器通常只允许 HTTPS 或 localhost 使用麦克风。

### 14.4 识别结果有重复

优先检查 `FunAsrRealtimeAsrProxy._concat_text()` 和 `normalize_funasr_event()`。

原则：

```text
2pass-online 只用于 preview
2pass-offline 才提交到 committed_text
```

---

## 15. 最终交付物

AI 代码编辑完成后，需要交付：

1. 修改后的 `docker-compose.yml`。
2. 修改后的 `backend/config/settings.py`。
3. 修改后的 `backend/config/.env.example`。
4. 修改后的 `backend/services/asr_service.py`。
5. 修改后的 `backend/api/routes/asr.py`。
6. 一组启动命令和测试结果截图或日志。

最终启动命令：

```bash
docker compose config
docker compose pull funasr
docker compose up -d funasr
docker compose up -d --build backend frontend
docker compose logs -f funasr
```
