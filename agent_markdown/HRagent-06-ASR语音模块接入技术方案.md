# HRagent-06 对话预演页语音转文字模块接入技术方案

> 目标：在 `frontend/src/pages/steps/RehearsalStep.tsx` 的“对话预演”页面中，把现有麦克风占位按钮升级为可用的实时语音输入模块，实现“点击麦克风 → 说话 → 快速转文字 → 回填输入框 → 用户确认后发送”。
>
> 推荐方案：**浏览器采集麦克风音频 + 前端 WebSocket 传 PCM 音频帧 + FastAPI WebSocket 后端代理 + Qwen3-ASR-Flash-Realtime 实时识别**。

---

## 1. 一句话结论

当前项目最适合采用：

```text
React 19 + TypeScript + Web Audio API + AudioWorklet
        ↓
FastAPI WebSocket 后端代理
        ↓
阿里云百炼 Qwen3-ASR-Flash-Realtime
        ↓
partial/final transcript 回填 RehearsalStep 输入框
```

不要让浏览器直接连接阿里云 ASR，因为 API Key 不能暴露在前端。后端必须作为 **安全代理层** 负责鉴权、限流、日志、错误处理和企业内网代理适配。

---

## 2. 当前项目基础判断

根据上传的 `HRagent-06` 项目结构，当前已有能力如下：

| 层级 | 已有能力 | 说明 |
|---|---|---|
| 前端框架 | React 19 + TypeScript + Vite | `frontend/package.json` 已具备 |
| 对话页面 | `frontend/src/pages/steps/RehearsalStep.tsx` | 当前页面底部已有麦克风按钮，但逻辑为占位 Toast |
| API 封装 | `frontend/src/api/client.ts` | 当前已有 REST/SSE API 封装 |
| 后端框架 | FastAPI + Uvicorn | `backend/main.py` 统一挂载 routes |
| 流式输出 | SSE | 已用于 guidance/rehearsal/report 流式输出 |
| 反向代理 | Nginx | `frontend/nginx.conf` 已代理 `/api/v1/` 到后端 |
| 容器 | Docker Compose | backend/frontend/postgres/redis/mineru 已配置 |

当前最小改造点：

```text
1. RehearsalStep.tsx：替换麦克风占位逻辑
2. frontend/src/hooks/useRealtimeAsr.ts：新增语音识别 Hook
3. frontend/public/asr-pcm-worklet.js：新增音频处理 Worklet
4. backend/api/routes/asr.py：新增 FastAPI WebSocket 路由
5. backend/services/asr_service.py：新增 Qwen ASR 后端代理服务
6. backend/schemas/asr.py：新增 ASR 事件 Schema
7. backend/config/settings.py：新增 ASR 配置项
8. backend/config/.env.example：新增 ASR 环境变量
9. backend/requirements.txt：新增 websockets 依赖
10. frontend/nginx.conf：补充 WebSocket Upgrade 代理头
11. backend/main.py：挂载 asr.router
```

---

## 3. 业务目标

### 3.1 用户侧体验

用户在“对话预演”页面中：

```text
点击麦克风按钮
  ↓
浏览器请求麦克风权限
  ↓
开始录音，按钮进入红色/录音中状态
  ↓
用户说话，输入框实时出现转写文本
  ↓
再次点击麦克风停止录音
  ↓
最终转写文本保留在输入框
  ↓
用户检查文字后点击“发送”
```

### 3.2 不做自动发送

第一版不要做“语音识别完成后自动发送”。绩效反馈、PIP、离职倾向、冲突沟通等 HR 对话场景对措辞敏感，必须让用户确认 ASR 转写结果后再发送。

### 3.3 识别目标

| 目标 | 要求 |
|---|---|
| 低延迟 | 说话过程中尽快显示 partial 文本 |
| 中文优先 | 默认 `language=zh` |
| HR 术语可扩展 | 后续可加术语纠错：HRBP、HOD、PMP、Bosch、绩效、rating 等 |
| 不保存原始音频 | 后端只转发音频流，默认不落盘 |
| 安全 | ASR API Key 只在后端 `.env` 中配置 |

---

## 4. 推荐模型与调用方式

### 4.1 首选模型

```text
qwen3-asr-flash-realtime
```

理由：当前页面要求“快速语音转文字输出”，属于实时 ASR 场景。`qwen3-asr-flash` 更适合非实时/文件或短音频识别，实时对话输入应使用 `qwen3-asr-flash-realtime`。

### 4.2 连接方式

后端连接阿里云百炼 Qwen ASR Realtime WebSocket：

```text
ASR_WS_URL + ?model=qwen3-asr-flash-realtime
```

典型配置：

```text
Authorization: Bearer ${ASR_API_KEY}
OpenAI-Beta: realtime=v1
```

### 4.3 音频格式

推荐统一为：

```text
format: pcm
sample_rate: 16000
channels: 1
sample_width: 16-bit
encoding: PCM16 little-endian
chunk: 20ms - 100ms
```

前端浏览器麦克风通常采样率为 48000Hz，因此需要在 `AudioWorklet` 中降采样到 16000Hz，并转换成 PCM16。

---

## 5. 目标架构

```text
┌─────────────────────────────────────────────────────────────┐
│ Frontend: RehearsalStep.tsx                                 │
│ - 麦克风按钮                                                  │
│ - 输入框 textarea                                             │
│ - useRealtimeAsr Hook                                        │
└─────────────────────────────────────────────────────────────┘
                    │
                    │ getUserMedia + AudioWorklet
                    ↓
┌─────────────────────────────────────────────────────────────┐
│ Browser Audio Pipeline                                      │
│ - capture microphone stream                                 │
│ - resample to 16kHz mono                                     │
│ - convert Float32 → PCM16                                    │
│ - send binary frames via WebSocket                           │
└─────────────────────────────────────────────────────────────┘
                    │
                    │ ws://localhost:7070/api/v1/asr/realtime
                    ↓
┌─────────────────────────────────────────────────────────────┐
│ Backend: FastAPI WebSocket                                  │
│ - receive binary PCM16 frames                                │
│ - protect ASR API Key                                        │
│ - connect Qwen ASR Realtime                                  │
│ - forward audio by input_audio_buffer.append                 │
│ - normalize partial/final events                             │
└─────────────────────────────────────────────────────────────┘
                    │
                    │ wss://...maas.aliyuncs.com/api-ws/v1/realtime?model=...
                    ↓
┌─────────────────────────────────────────────────────────────┐
│ Qwen3-ASR-Flash-Realtime                                    │
│ - session.update                                             │
│ - input_audio_buffer.append                                  │
│ - conversation.item.input_audio_transcription.text            │
│ - conversation.item.input_audio_transcription.completed       │
│ - session.finish                                             │
└─────────────────────────────────────────────────────────────┘
                    │
                    │ normalized JSON
                    ↓
┌─────────────────────────────────────────────────────────────┐
│ Frontend UI                                                  │
│ - partial: 实时预览文本                                       │
│ - final: 回填输入框                                           │
│ - user manually clicks Send                                  │
└─────────────────────────────────────────────────────────────┘
```

---

## 6. 技术栈清单

### 6.1 前端技术栈

| 技术 | 用途 | 是否新增依赖 |
|---|---|---|
| React 19 | 页面状态管理 | 已有 |
| TypeScript | 类型约束 | 已有 |
| Vite | 前端构建 | 已有 |
| WebSocket | 与后端 ASR 通道通信 | 浏览器原生，无需新增 |
| `navigator.mediaDevices.getUserMedia` | 获取麦克风权限 | 浏览器原生 |
| Web Audio API | 创建音频处理图 | 浏览器原生 |
| AudioWorklet | 低延迟音频处理 | 浏览器原生 |
| PCM16 编码 | ASR 输入格式 | 自定义代码 |

前端不需要新增 npm 依赖。

### 6.2 后端技术栈

| 技术 | 用途 | 是否新增依赖 |
|---|---|---|
| FastAPI WebSocket | 接收浏览器音频流 | 已有 FastAPI |
| `websockets` | 后端连接 Qwen ASR Realtime | 新增 |
| Pydantic Settings | ASR 配置管理 | 已有 |
| asyncio | 双向转发音频与识别结果 | Python 标准库 |
| base64 | PCM 二进制音频转 Qwen JSON 字段 | Python 标准库 |
| Nginx WebSocket proxy | 前端容器转发 WS 到 backend | 修改配置 |

新增后端依赖：

```txt
websockets>=13.0
```

---

## 7. 环境变量设计

修改：`backend/config/.env.example`

新增：

```env
# =========================
# ASR / Speech-to-Text
# =========================
ASR_ENABLED=true
ASR_PROVIDER=qwen
ASR_MODEL=qwen3-asr-flash-realtime

# 阿里云百炼 API Key。只允许放后端，不允许放前端。
ASR_API_KEY=sk-xxx

# 从百炼控制台复制对应地域和 Workspace 的 Realtime WebSocket URL。
# 示例结构：wss://{WorkspaceId}.<region>.maas.aliyuncs.com/api-ws/v1/realtime
ASR_WS_URL=wss://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime

ASR_LANGUAGE=zh
ASR_SAMPLE_RATE=16000
ASR_INPUT_AUDIO_FORMAT=pcm
ASR_ENABLE_SERVER_VAD=true
ASR_VAD_THRESHOLD=0.0
ASR_VAD_SILENCE_DURATION_MS=400
ASR_CONNECT_TIMEOUT_SECONDS=15
ASR_SESSION_TIMEOUT_SECONDS=120
ASR_MAX_SESSION_SECONDS=300
```

生产环境注意：

```text
1. ASR_API_KEY 不要提交到 Git。
2. 北京和新加坡地域 API Key 可能不同，需要使用对应地域的 Key。
3. ASR_WS_URL 不要硬编码在代码里，应走环境变量。
4. 公司代理环境下，backend 容器需要能访问阿里云 WebSocket 域名。
```

---

## 8. 后端改造设计

### 8.1 修改 `backend/config/settings.py`

在 `Settings` 类中新增字段，必须提供默认值，避免旧 `.env` 不包含 ASR 配置时启动失败。

```python
# ASR / Speech-to-Text
asr_enabled: bool = True
asr_provider: Literal["qwen"] = "qwen"
asr_model: str = "qwen3-asr-flash-realtime"
asr_api_key: str = ""
asr_ws_url: str = ""
asr_language: str = "zh"
asr_sample_rate: int = 16000
asr_input_audio_format: str = "pcm"
asr_enable_server_vad: bool = True
asr_vad_threshold: float = 0.0
asr_vad_silence_duration_ms: int = 400
asr_connect_timeout_seconds: float = 15.0
asr_session_timeout_seconds: float = 120.0
asr_max_session_seconds: int = 300
```

可选新增属性：

```python
@property
def asr_realtime_url(self) -> str:
    base = self.asr_ws_url.strip()
    if not base:
        return ""
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}model={self.asr_model}"
```

### 8.2 新增 `backend/schemas/asr.py`

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class AsrFrontendEvent(BaseModel):
    type: Literal["status", "partial", "final", "error"]
    text: str | None = None
    preview: str | None = None
    transcript: str | None = None
    emotion: str | None = None
    message: str | None = None
    code: str | None = None


class AsrControlEvent(BaseModel):
    type: Literal["start", "stop", "ping"]
    language: str | None = None
```

### 8.3 新增 `backend/services/asr_service.py`

职责：

```text
1. 校验 ASR 配置是否完整
2. 建立到 Qwen ASR Realtime 的 WebSocket
3. 发送 session.update
4. 将浏览器传来的 PCM bytes 转 base64
5. 发送 input_audio_buffer.append
6. 接收 Qwen ASR 事件
7. 统一成前端事件：status / partial / final / error
8. 结束时发送 session.finish
```

核心伪代码：

```python
from __future__ import annotations

import asyncio
import base64
import json
import time
from typing import Any, Awaitable, Callable

import websockets
from websockets.exceptions import ConnectionClosed

from backend.config.settings import Settings

SendFrontend = Callable[[dict[str, Any]], Awaitable[None]]


class AsrConfigurationError(RuntimeError):
    pass


class QwenRealtimeAsrProxy:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._qwen_ws = None
        self._started_at = time.monotonic()
        self._closed = False

    def validate(self) -> None:
        if not self.settings.asr_enabled:
            raise AsrConfigurationError("ASR is disabled")
        if not self.settings.asr_api_key:
            raise AsrConfigurationError("ASR_API_KEY is empty")
        if not self.settings.asr_ws_url:
            raise AsrConfigurationError("ASR_WS_URL is empty")

    def _qwen_url(self) -> str:
        base = self.settings.asr_ws_url.strip()
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}model={self.settings.asr_model}"

    async def connect(self) -> None:
        self.validate()
        self._qwen_ws = await websockets.connect(
            self._qwen_url(),
            additional_headers={
                "Authorization": f"Bearer {self.settings.asr_api_key}",
                "OpenAI-Beta": "realtime=v1",
            },
            open_timeout=self.settings.asr_connect_timeout_seconds,
            ping_interval=20,
            ping_timeout=20,
            max_size=8 * 1024 * 1024,
        )
        await self._send_session_update()

    async def _send_json(self, payload: dict[str, Any]) -> None:
        if not self._qwen_ws:
            raise RuntimeError("Qwen ASR websocket is not connected")
        await self._qwen_ws.send(json.dumps(payload, ensure_ascii=False))

    async def _send_session_update(self) -> None:
        session: dict[str, Any] = {
            "modalities": ["text"],
            "input_audio_format": self.settings.asr_input_audio_format,
            "sample_rate": self.settings.asr_sample_rate,
        }
        if self.settings.asr_language:
            session["input_audio_transcription"] = {"language": self.settings.asr_language}
        if self.settings.asr_enable_server_vad:
            session["turn_detection"] = {
                "type": "server_vad",
                "threshold": self.settings.asr_vad_threshold,
                "silence_duration_ms": self.settings.asr_vad_silence_duration_ms,
            }
        else:
            session["turn_detection"] = None

        await self._send_json({
            "event_id": f"session_update_{int(time.time() * 1000)}",
            "type": "session.update",
            "session": session,
        })

    async def append_audio(self, pcm_bytes: bytes) -> None:
        if self._closed:
            return
        if time.monotonic() - self._started_at > self.settings.asr_max_session_seconds:
            raise TimeoutError("ASR session exceeded maximum duration")
        if not pcm_bytes:
            return
        audio_b64 = base64.b64encode(pcm_bytes).decode("ascii")
        await self._send_json({
            "event_id": f"audio_{int(time.time() * 1000)}",
            "type": "input_audio_buffer.append",
            "audio": audio_b64,
        })

    async def finish(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if not self.settings.asr_enable_server_vad:
                await self._send_json({
                    "event_id": f"commit_{int(time.time() * 1000)}",
                    "type": "input_audio_buffer.commit",
                })
            await self._send_json({
                "event_id": f"finish_{int(time.time() * 1000)}",
                "type": "session.finish",
            })
        except Exception:
            pass

    async def close(self) -> None:
        self._closed = True
        if self._qwen_ws:
            await self._qwen_ws.close(code=1000, reason="client closed")

    async def receive_loop(self, send_frontend: SendFrontend) -> None:
        if not self._qwen_ws:
            raise RuntimeError("Qwen ASR websocket is not connected")
        async for raw in self._qwen_ws:
            data = json.loads(raw)
            normalized = self.normalize_qwen_event(data)
            if normalized:
                await send_frontend(normalized)
            if data.get("type") == "session.finished":
                break

    @staticmethod
    def normalize_qwen_event(data: dict[str, Any]) -> dict[str, Any] | None:
        event_type = data.get("type")
        if event_type == "session.created":
            return {"type": "status", "message": "ASR session created"}
        if event_type == "input_audio_buffer.speech_started":
            return {"type": "status", "code": "speech_started", "message": "speech_started"}
        if event_type == "input_audio_buffer.speech_stopped":
            return {"type": "status", "code": "speech_stopped", "message": "speech_stopped"}
        if event_type == "conversation.item.input_audio_transcription.text":
            text = str(data.get("text") or "")
            stash = str(data.get("stash") or "")
            return {
                "type": "partial",
                "text": text,
                "preview": f"{text}{stash}",
                "emotion": data.get("emotion"),
            }
        if event_type == "conversation.item.input_audio_transcription.completed":
            return {
                "type": "final",
                "transcript": str(data.get("transcript") or ""),
                "emotion": data.get("emotion"),
            }
        if event_type == "error":
            return {
                "type": "error",
                "message": str(data.get("message") or data),
            }
        return None
```

> 注意：不同版本的 `websockets` 参数名可能有差异。如果安装版本低于 13，`additional_headers` 可能需要改成 `extra_headers`。建议直接安装 `websockets>=13.0`。

### 8.4 新增 `backend/api/routes/asr.py`

```python
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.config.settings import get_settings
from backend.services.asr_service import AsrConfigurationError, QwenRealtimeAsrProxy

router = APIRouter(tags=["asr"])


@router.websocket("/asr/realtime")
async def asr_realtime(websocket: WebSocket) -> None:
    await websocket.accept()
    settings = get_settings()
    proxy = QwenRealtimeAsrProxy(settings)

    async def send_frontend(payload: dict) -> None:
        await websocket.send_text(json.dumps(payload, ensure_ascii=False))

    try:
        await proxy.connect()
        await send_frontend({"type": "status", "message": "ASR connected"})

        receive_task = asyncio.create_task(proxy.receive_loop(send_frontend))

        while True:
            message = await websocket.receive()
            if message.get("bytes") is not None:
                await proxy.append_audio(message["bytes"] or b"")
                continue

            if message.get("text") is not None:
                try:
                    data = json.loads(message["text"] or "{}")
                except json.JSONDecodeError:
                    continue
                event_type = data.get("type")
                if event_type == "stop":
                    await proxy.finish()
                    break
                if event_type == "ping":
                    await send_frontend({"type": "status", "message": "pong"})

            if receive_task.done():
                break

        await proxy.finish()
        try:
            await asyncio.wait_for(receive_task, timeout=3)
        except asyncio.TimeoutError:
            receive_task.cancel()

    except WebSocketDisconnect:
        pass
    except AsrConfigurationError as exc:
        await send_frontend({"type": "error", "message": str(exc)})
    except Exception as exc:
        await send_frontend({"type": "error", "message": f"ASR failed: {exc}"})
    finally:
        await proxy.close()
```

### 8.5 修改 `backend/main.py`

原导入：

```python
from backend.api.routes import documents, employees, guidance, health, rehearsal, reports, sessions, setup
```

改为：

```python
from backend.api.routes import asr, documents, employees, guidance, health, rehearsal, reports, sessions, setup
```

原 router 列表中加入 `asr.router`：

```python
for router in [
    health.router,
    sessions.router,
    documents.router,
    employees.router,
    setup.router,
    guidance.router,
    rehearsal.router,
    reports.router,
    asr.router,
]:
    app.include_router(router, prefix=settings.api_prefix)
```

### 8.6 修改 `backend/requirements.txt`

新增一行：

```txt
websockets>=13.0
```

---

## 9. Nginx 改造设计

修改：`frontend/nginx.conf`

当前 `/api/v1/` 已有反向代理，但需要补充 WebSocket Upgrade 头。

推荐改为：

```nginx
location /api/v1/ {
  proxy_pass http://backend:7111/api/v1/;
  proxy_http_version 1.1;

  proxy_set_header Upgrade $http_upgrade;
  proxy_set_header Connection "upgrade";

  proxy_set_header Host $host;
  proxy_set_header X-Real-IP $remote_addr;
  proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
  proxy_set_header X-Forwarded-Proto $scheme;

  proxy_connect_timeout 86400s;
  proxy_send_timeout 86400s;
  proxy_read_timeout 86400s;
  send_timeout 86400s;
  proxy_buffering off;
}
```

如未来需要更规范，可增加 `map`：

```nginx
map $http_upgrade $connection_upgrade {
  default upgrade;
  '' close;
}
```

然后：

```nginx
proxy_set_header Connection $connection_upgrade;
```

当前项目先使用简单版即可。

---

## 10. 前端改造设计

### 10.1 修改 `frontend/src/api/client.ts`

新增 WebSocket Base URL 方法：

```ts
export function getWsApiBase(): string {
  const apiBase = getApiBase();
  const url = new URL(apiBase, window.location.origin);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  return url.toString().replace(/\/$/, '');
}
```

使用方式：

```ts
const ws = new WebSocket(`${getWsApiBase()}/asr/realtime`);
```

### 10.2 新增 `frontend/public/asr-pcm-worklet.js`

作用：

```text
1. 接收浏览器麦克风 Float32 音频帧
2. 按 AudioContext 实际 sampleRate 降采样到 16000Hz
3. 转成 Int16 PCM little-endian
4. 通过 port.postMessage 发送 ArrayBuffer 给主线程
```

参考实现：

```js
class AsrPcmWorkletProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.targetSampleRate = 16000;
    this.buffer = [];
    this.inputSampleRate = sampleRate;
    this.ratio = this.inputSampleRate / this.targetSampleRate;
    this._lastIndex = 0;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || !input[0]) return true;

    const channel = input[0];
    for (let i = 0; i < channel.length; i += this.ratio) {
      const idx = Math.floor(i);
      const sample = Math.max(-1, Math.min(1, channel[idx] || 0));
      const int16 = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
      this.buffer.push(int16 | 0);
    }

    // 1600 samples = 100ms @ 16kHz
    if (this.buffer.length >= 1600) {
      const samples = this.buffer.splice(0, 1600);
      const pcm = new Int16Array(samples.length);
      for (let i = 0; i < samples.length; i += 1) {
        pcm[i] = samples[i];
      }
      this.port.postMessage(pcm.buffer, [pcm.buffer]);
    }

    return true;
  }
}

registerProcessor('asr-pcm-worklet', AsrPcmWorkletProcessor);
```

### 10.3 新增 `frontend/src/hooks/useRealtimeAsr.ts`

职责：

```text
1. start(): 请求麦克风权限，连接后端 ASR WebSocket，启动 AudioWorklet
2. stop(): 停止录音，发送 stop 事件，释放麦克风轨道
3. 自动接收后端 partial/final/error 事件
4. 把识别文本回传给 RehearsalStep
5. 管理状态：idle / connecting / recording / error
```

参考实现：

```ts
import { useCallback, useRef, useState } from 'react';
import { getWsApiBase } from '../api/client';

type AsrStatus = 'idle' | 'connecting' | 'recording' | 'error';

type AsrServerEvent = {
  type: 'status' | 'partial' | 'final' | 'error';
  text?: string;
  preview?: string;
  transcript?: string;
  emotion?: string;
  message?: string;
  code?: string;
};

type UseRealtimeAsrOptions = {
  onPartialTranscript?: (text: string, event: AsrServerEvent) => void;
  onFinalTranscript?: (text: string, event: AsrServerEvent) => void;
  onError?: (message: string) => void;
};

export function useRealtimeAsr(options: UseRealtimeAsrOptions = {}) {
  const [status, setStatus] = useState<AsrStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const workletRef = useRef<AudioWorkletNode | null>(null);

  const cleanup = useCallback(async () => {
    workletRef.current?.disconnect();
    sourceRef.current?.disconnect();

    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;

    if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
      await audioContextRef.current.close();
    }
    audioContextRef.current = null;

    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'stop' }));
      wsRef.current.close(1000, 'client stop');
    }
    wsRef.current = null;
  }, []);

  const stop = useCallback(async () => {
    await cleanup();
    setStatus('idle');
  }, [cleanup]);

  const start = useCallback(async () => {
    try {
      setError(null);
      setStatus('connecting');

      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error('当前浏览器不支持麦克风录音。');
      }

      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          noiseSuppression: true,
          echoCancellation: true,
          autoGainControl: true,
        },
        video: false,
      });
      streamRef.current = stream;

      const ws = new WebSocket(`${getWsApiBase()}/asr/realtime`);
      ws.binaryType = 'arraybuffer';
      wsRef.current = ws;

      await new Promise<void>((resolve, reject) => {
        const timer = window.setTimeout(() => reject(new Error('ASR WebSocket 连接超时。')), 10000);
        ws.onopen = () => {
          window.clearTimeout(timer);
          resolve();
        };
        ws.onerror = () => {
          window.clearTimeout(timer);
          reject(new Error('ASR WebSocket 连接失败。'));
        };
      });

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as AsrServerEvent;
          if (data.type === 'partial') {
            const text = data.preview || data.text || '';
            if (text) options.onPartialTranscript?.(text, data);
          }
          if (data.type === 'final') {
            const text = data.transcript || '';
            if (text) options.onFinalTranscript?.(text, data);
          }
          if (data.type === 'error') {
            const message = data.message || '语音识别失败。';
            setError(message);
            setStatus('error');
            options.onError?.(message);
          }
        } catch {
          // ignore malformed message
        }
      };

      const audioContext = new AudioContext();
      audioContextRef.current = audioContext;
      await audioContext.audioWorklet.addModule('/asr-pcm-worklet.js');

      const source = audioContext.createMediaStreamSource(stream);
      const worklet = new AudioWorkletNode(audioContext, 'asr-pcm-worklet');
      source.connect(worklet);
      sourceRef.current = source;
      workletRef.current = worklet;

      worklet.port.onmessage = (event) => {
        const socket = wsRef.current;
        if (socket && socket.readyState === WebSocket.OPEN) {
          socket.send(event.data as ArrayBuffer);
        }
      };

      setStatus('recording');
    } catch (err) {
      const message = err instanceof Error ? err.message : '语音输入启动失败。';
      setError(message);
      setStatus('error');
      options.onError?.(message);
      await cleanup();
    }
  }, [cleanup, options]);

  return {
    status,
    error,
    isRecording: status === 'recording',
    isConnecting: status === 'connecting',
    start,
    stop,
  };
}
```

### 10.4 修改 `frontend/src/pages/steps/RehearsalStep.tsx`

新增导入：

```ts
import { useRealtimeAsr } from '../../hooks/useRealtimeAsr';
```

在组件中新增：

```ts
const asr = useRealtimeAsr({
  onPartialTranscript: (text) => {
    setMessage(text);
  },
  onFinalTranscript: (text) => {
    setMessage(text);
  },
  onError: (msg) => {
    showToast(msg, 'error');
  },
});
```

修改 `submit`，发送前可停止录音：

```ts
const submit = async () => {
  const text = message.trim();
  if (!text) return;
  if (asr.isRecording || asr.isConnecting) await asr.stop();
  setMessage('');
  await sendMessage(text);
};
```

替换当前麦克风按钮：

```tsx
<button
  className={`mic-button ${asr.isRecording ? 'recording' : ''} ${asr.isConnecting ? 'connecting' : ''}`}
  title={asr.isRecording ? '停止语音输入' : '开始语音输入'}
  aria-label={asr.isRecording ? '停止语音输入' : '开始语音输入'}
  type="button"
  disabled={rehearsalStreaming || asr.isConnecting}
  onClick={() => {
    if (asr.isRecording) void asr.stop();
    else void asr.start();
  }}
>
  <span className="mic-icon" aria-hidden="true">
    <svg viewBox="0 0 24 24" focusable="false">
      <path d="M12 3.75a3.25 3.25 0 0 0-3.25 3.25v4.1a3.25 3.25 0 0 0 6.5 0V7A3.25 3.25 0 0 0 12 3.75Z" />
      <path d="M6.25 10.75a.75.75 0 0 1 1.5 0v.35a4.25 4.25 0 0 0 8.5 0v-.35a.75.75 0 0 1 1.5 0v.35a5.76 5.76 0 0 1-5 5.71v1.69h2.1a.75.75 0 0 1 0 1.5h-5.7a.75.75 0 0 1 0-1.5h2.1v-1.69a5.76 5.76 0 0 1-5-5.71v-.35Z" />
    </svg>
  </span>
</button>
```

在 `message-bar` 下方可选新增状态提示：

```tsx
{asr.isRecording && <div className="asr-hint">正在聆听，转写结果会实时填入输入框。</div>}
{asr.isConnecting && <div className="asr-hint">正在连接语音识别服务...</div>}
```

### 10.5 修改 `frontend/src/styles/global.css`

新增：

```css
.mic-button.recording {
  color: #fff;
  background: var(--bosch-red, #e20015);
  border-color: var(--bosch-red, #e20015);
}

.mic-button.connecting {
  color: #fff;
  background: var(--bosch-blue, #007bc0);
  border-color: var(--bosch-blue, #007bc0);
}

.asr-hint {
  margin-top: 6px;
  font-size: 12px;
  color: var(--text-muted, #687480);
}
```

如果 `message-bar` 当前不适合放状态提示，可以先不加 `asr-hint`，仅通过按钮颜色和 Toast 反馈状态。

---

## 11. 前后端事件协议

### 11.1 前端 → 后端

二进制音频帧：

```text
WebSocket binary frame: PCM16 little-endian bytes, 16kHz, mono
```

停止事件：

```json
{
  "type": "stop"
}
```

心跳事件：

```json
{
  "type": "ping"
}
```

### 11.2 后端 → 前端

连接状态：

```json
{
  "type": "status",
  "message": "ASR connected"
}
```

中间转写：

```json
{
  "type": "partial",
  "text": "我觉得这一年",
  "preview": "我觉得这一年确实压力很大",
  "emotion": "neutral"
}
```

最终转写：

```json
{
  "type": "final",
  "transcript": "我觉得这一年确实压力很大，但我也希望能有更具体的反馈。",
  "emotion": "neutral"
}
```

错误：

```json
{
  "type": "error",
  "message": "ASR_API_KEY is empty"
}
```

---

## 12. 语音术语后处理设计（P1 可做）

第一版先不做，第二版建议增加 HR/Bosch 术语纠错。

新增文件：

```text
backend/services/asr_postprocess.py
```

示例：

```python
TERM_REPLACEMENTS = {
    "hr bp": "HRBP",
    "h r b p": "HRBP",
    "hod": "HOD",
    "p m p": "PMP",
    "博世": "Bosch",
    "boss": "Bosch",
    "rating": "Rating",
}


def normalize_asr_text(text: str) -> str:
    result = text
    for wrong, right in TERM_REPLACEMENTS.items():
        result = result.replace(wrong, right)
    return result
```

可在后端 `normalize_qwen_event` 输出前调用，也可以在前端 final 时处理。建议后端处理，保持统一。

---

## 13. 安全与合规要求

必须遵守：

```text
1. 不允许把 ASR_API_KEY 写入前端代码。
2. 不允许把 ASR_API_KEY 写入 Git。
3. 前端只连接自己的后端 `/api/v1/asr/realtime`。
4. 后端默认不保存原始音频。
5. 日志中不要打印完整转写文本，最多打印长度、状态、错误类型。
6. 用户点击麦克风时必须由浏览器弹出权限授权。
7. 生产或服务器访问时需要 HTTPS，否则浏览器可能不允许麦克风权限。
8. 绩效反馈场景下，不做自动发送，用户确认后再发送。
```

建议日志字段：

```text
session_id: 可选
asr_provider: qwen
model: qwen3-asr-flash-realtime
duration_seconds: 语音输入时长
status: success/error
error_code: 可选
```

不要记录：

```text
原始音频 bytes
完整转写文本
员工隐私信息
API Key
```

---

## 14. 测试方案

### 14.1 后端启动检查

```bash
cd HRagent-06

docker compose build backend frontend

docker compose up -d backend frontend

docker compose logs -f backend
```

检查：

```text
1. backend 正常启动
2. settings 不因缺少 ASR 环境变量而报错
3. nginx 正常启动
4. 浏览器可以打开 http://localhost:7070
```

### 14.2 WebSocket 路由检查

浏览器页面打开后点击麦克风，后端日志应看到：

```text
ASR connected
session.created
partial/final event
```

如果报错：

| 错误 | 可能原因 |
|---|---|
| `ASR_API_KEY is empty` | `.env` 未配置 API Key |
| `ASR_WS_URL is empty` | `.env` 未配置 WebSocket URL |
| WebSocket 连接失败 | Nginx 未配置 Upgrade，或后端路由未挂载 |
| 浏览器无麦克风权限 | 非 HTTPS、浏览器禁用权限、远程 HTTP 访问 |
| 阿里云连接失败 | API Key 地域不匹配、WorkspaceId 不正确、公司代理无法访问 WSS |

### 14.3 前端交互测试

测试用例：

```text
1. 点击麦克风，浏览器弹出权限申请。
2. 授权后，按钮变为录音中状态。
3. 说一句中文：“我觉得这一年的绩效没有达到预期。”
4. 输入框实时出现文字。
5. 点击麦克风停止，最终文本保留在输入框。
6. 点击发送，对话继续。
7. 回复中状态下麦克风不可点击。
8. 网络断开时 Toast 提示语音识别失败。
```

### 14.4 兼容性测试

| 场景 | 预期 |
|---|---|
| Chrome 本地访问 `localhost:7070` | 可请求麦克风 |
| Edge 本地访问 `localhost:7070` | 可请求麦克风 |
| 服务器 HTTP IP 访问 | 可能无法请求麦克风 |
| HTTPS 域名访问 | 可请求麦克风 |
| 用户拒绝麦克风权限 | 显示错误 Toast |
| ASR Key 错误 | 后端返回 error，前端 Toast |

---

## 15. 开发顺序

### P0：最小可用版本

按此顺序让 AI coding：

```text
1. backend/requirements.txt 增加 websockets
2. backend/config/settings.py 增加 ASR 配置字段
3. backend/schemas/asr.py 新增 Schema
4. backend/services/asr_service.py 新增 QwenRealtimeAsrProxy
5. backend/api/routes/asr.py 新增 WebSocket route
6. backend/main.py include asr.router
7. frontend/nginx.conf 增加 WebSocket Upgrade 头
8. frontend/src/api/client.ts 新增 getWsApiBase
9. frontend/public/asr-pcm-worklet.js 新增 AudioWorklet
10. frontend/src/hooks/useRealtimeAsr.ts 新增 Hook
11. frontend/src/pages/steps/RehearsalStep.tsx 接入 Hook
12. frontend/src/styles/global.css 增加 recording/connecting 样式
13. docker compose build && docker compose up 测试
```

### P1：体验增强

```text
1. 显示 “正在聆听 / 正在转写 / 已完成” 状态
2. 识别中禁止重复点击发送
3. 添加 ASR 术语纠错
4. 统计语音时长和成本
5. 增加重连和超时处理
```

### P2：企业可用

```text
1. ASR 并发限流
2. 审计日志
3. 权限控制
4. 敏感词和红线检测联动
5. 可切换 Qwen ASR / Fun-ASR / Paraformer
6. 支持热词配置
```

---

## 16. AI Coding 专用任务指令

可以把下面这段直接交给代码生成 AI：

```text
请在 HRagent-06 项目中为“对话预演”页面添加实时语音转文字模块。项目当前前端为 React 19 + TypeScript + Vite，后端为 FastAPI，页面文件是 frontend/src/pages/steps/RehearsalStep.tsx。该页面底部已有 mic-button，但目前只显示“语音输入不在本次 POC 范围内”的 Toast，需要替换为真实语音输入功能。

总体方案：浏览器使用 navigator.mediaDevices.getUserMedia 获取麦克风音频，通过 AudioWorklet 将音频降采样为 16kHz 单声道 PCM16，小块二进制帧通过 WebSocket 发送到后端 /api/v1/asr/realtime。后端使用 FastAPI WebSocket 接收音频帧，再用 websockets 连接阿里云百炼 Qwen3-ASR-Flash-Realtime WebSocket，发送 session.update、input_audio_buffer.append、session.finish，并将 Qwen 的 partial/final 结果规范化后返回前端。前端将 partial/final 文本实时回填 textarea，但不要自动发送，必须由用户确认后点击“发送”。

请完成以下文件修改：
1. backend/requirements.txt：增加 websockets>=13.0。
2. backend/config/settings.py：增加 ASR 配置字段，字段必须有默认值，避免旧 env 启动失败。
3. backend/config/.env.example：增加 ASR_ENABLED、ASR_MODEL、ASR_API_KEY、ASR_WS_URL、ASR_LANGUAGE、ASR_SAMPLE_RATE、ASR_ENABLE_SERVER_VAD 等配置。
4. 新增 backend/schemas/asr.py，定义 ASR 前端事件 Schema。
5. 新增 backend/services/asr_service.py，实现 QwenRealtimeAsrProxy，负责连接 Qwen ASR Realtime、发送 session.update、转发音频、接收并规范化转写事件。
6. 新增 backend/api/routes/asr.py，提供 @router.websocket("/asr/realtime")。
7. 修改 backend/main.py，导入并 include asr.router。
8. 修改 frontend/nginx.conf，为 /api/v1/ 增加 WebSocket Upgrade 和 Connection header。
9. 修改 frontend/src/api/client.ts，新增 getWsApiBase()。
10. 新增 frontend/public/asr-pcm-worklet.js，用 AudioWorklet 完成 Float32 -> 16kHz PCM16。
11. 新增 frontend/src/hooks/useRealtimeAsr.ts，封装 start/stop/status/error/isRecording/isConnecting。
12. 修改 frontend/src/pages/steps/RehearsalStep.tsx，把 mic-button 的占位 onClick 替换为 useRealtimeAsr 的 start/stop。partial/final 都调用 setMessage(text)。发送消息前如果正在录音，先 stop。
13. 修改 frontend/src/styles/global.css，增加 .mic-button.recording、.mic-button.connecting、.asr-hint 样式。

后端连接 Qwen ASR 时：
- URL 使用 ASR_WS_URL + '?model=' + ASR_MODEL。
- 请求头包含 Authorization: Bearer ${ASR_API_KEY} 和 OpenAI-Beta: realtime=v1。
- session.update 使用 modalities:['text']、input_audio_format:'pcm'、sample_rate:16000、turn_detection server_vad。
- 收到前端 bytes 后 base64 编码，发送 {type:'input_audio_buffer.append', audio: encoded}。
- 收到 stop 后发送 session.finish；如果关闭 server_vad，则先发送 input_audio_buffer.commit。
- 将 conversation.item.input_audio_transcription.text 转为 {type:'partial', preview:text+stash, emotion}。
- 将 conversation.item.input_audio_transcription.completed 转为 {type:'final', transcript, emotion}。

安全要求：
- 不允许把 API Key 放到前端。
- 不保存原始音频。
- 日志不要打印完整转写文本。
- 不要做自动发送，用户必须检查输入框后手动点击“发送”。

完成后确保：
- docker compose build backend frontend 通过。
- 前端 TypeScript build 通过。
- 点击麦克风后可以请求权限，录音中按钮有状态变化，识别结果能实时写入输入框。
```

---

## 17. 验收标准

### 功能验收

```text
[ ] 麦克风按钮不再显示 POC 占位 Toast
[ ] 点击后可以请求浏览器麦克风权限
[ ] 录音中按钮状态明显变化
[ ] 用户说话时输入框有实时转写文本
[ ] 停止录音后最终文本保留在输入框
[ ] 用户点击发送后，现有对话预演流程继续正常工作
[ ] 回复流式输出时，麦克风按钮不可用
```

### 安全验收

```text
[ ] 前端 bundle 中不存在 ASR_API_KEY
[ ] Git 中不存在真实 API Key
[ ] 后端不落盘原始音频
[ ] 日志不打印完整转写内容
[ ] 远程部署使用 HTTPS
```

### 工程验收

```text
[ ] backend 启动无 settings 校验错误
[ ] frontend tsc --noEmit 通过
[ ] docker compose build 通过
[ ] Nginx WebSocket 代理正常
[ ] ASR 错误能够显示 Toast
```

---

## 18. 成本与模型选择说明

你提到的 `¥0.00022/s` 更接近部分非实时或 Fun-ASR 价格。当前页面要求“边说边出字”，因此建议优先使用：

```text
qwen3-asr-flash-realtime
```

成本计算方式：

```text
单次语音输入成本 = 语音秒数 × 单价/秒
```

示例：

```text
10 分钟 = 600 秒
若单价 0.00033 元/秒，则成本约 0.198 元
若单价 0.00066 元/秒，则成本约 0.396 元
```

最终价格以实际阿里云百炼控制台地域和模型价格为准。

---

## 19. 最终推荐落地版本

最终推荐你先做：

```text
P0：qwen3-asr-flash-realtime + 后端代理 + 实时回填输入框 + 用户手动发送
```

不要一开始做：

```text
1. 自动发送
2. 保存音频
3. 多模型切换
4. 复杂热词 UI
5. 把 ASR 接入整个 Agent 工作流
```

先保证“语音输入能稳定转文字”，再逐步增强术语纠错、成本统计、审计日志和企业权限控制。
