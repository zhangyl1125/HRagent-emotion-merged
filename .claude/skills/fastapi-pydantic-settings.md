---
name: fastapi-pydantic-settings
description: FastAPI configuration management pattern using pydantic-settings. Use when designing a new FastAPI project's config layer, adding new config fields, or organizing settings by business domain.
triggers:
  - settings
  - config
  - 配置
  - pydantic-settings
  - BaseSettings
  - .env
  - 环境变量
  - get_settings
scope: Python / FastAPI projects
---

# FastAPI + Pydantic Settings 配置管理模式

来源：[backend/config/settings.py](../../backend/config/settings.py)

## 整体架构

```
Settings(BaseSettings)           # pydantic-settings，自动从 .env 加载
  └── get_settings()            # @lru_cache 单例工厂
       └── app = create_app()   # FastAPI 应用使用单例 settings
```

## Settings 类模板

```python
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the application."""

    model_config = SettingsConfigDict(
        env_file=("backend/config/.env", "backend/config/env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",  # 忽略未知环境变量
    )

    # === 基础信息 ===
    app_name: str = "My App"
    app_version: str = "0.1.0"
    environment: str = "local"
    api_prefix: str = "/api/v1"

    # === 项目路径 ===
    project_root: Path = Field(default_factory=lambda: Path(__file__).resolve().parents[2])

    # === 按业务域分组 ===
    # LLM
    llm_provider: Literal["openai_compatible", "custom"]
    chat_api_key: str
    chat_model: str = ""
    llm_temperature: float = 0.7
    llm_max_tokens: int | None = None
    llm_timeout_seconds: float = 120.0

    # Database
    database_url: str

    # Cache
    redis_url: str = ""
    cache_enabled: bool = True

    # === 计算属性：用 @property 做路径拼接、格式转换等 ===
    @property
    def data_dir(self) -> Path:
        return self.runtime_data_dir or self.project_root / "data"

    @property
    def chat_url(self) -> str:
        return self._resolve_url(
            explicit_endpoint=self.chat_api_endpoint,
            base_url=self.chat_api_base_url,
            default_path="/chat/completions",
        )

    # === 任务路由：根据 task_name 返回不同模型/参数 ===
    def model_for_task(self, task_name: str | None = None) -> str:
        mapping = {
            "profile": self.profile_model,
            "employee": self.employee_model,
        }
        if task_name and task_name in mapping and mapping[task_name]:
            return mapping[task_name]
        return self.default_chat_model

    def temperature_for_task(self, task_name: str | None = None) -> float:
        if task_name == "employee":
            return self.llm_employee_temperature
        return self.llm_temperature

    # === 内部辅助方法 ===
    @staticmethod
    def _resolve_url(explicit_endpoint: str, base_url: str, default_path: str) -> str:
        ...
```

## 单例工厂

```python
@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    # 确保必要的目录存在
    settings.runtime_dir.mkdir(parents=True, exist_ok=True)
    return settings
```

> `@lru_cache(maxsize=1)` 保证整个进程只有一个 Settings 实例，且 `.env` 只读取一次。

## 环境变量加载优先级

```python
env_file=("backend/config/.env", "backend/config/env", ".env")
```

优先加载 `backend/config/.env`，其次 `backend/config/env`，最后 `.env`。**先找到的生效**。

## 设计原则

1. **按业务域分组**：用注释分隔 LLM / Embedding / Rerank / Database / Cache / Auth / ASR / TTS 等，便于查找和维护。
2. **使用 Literal 约束枚举值**：`llm_provider: Literal["openai_compatible", "custom"]` 提供类型安全和 IDE 补全。
3. **敏感信息不给默认值**：API key、密码等字段声明类型但不设默认值，强制从 `.env` 读取。
4. **计算属性用 @property**：路径拼接、URL 构建、超时秒数转换等用 `@property`，保持配置源单一。
5. **任务路由用方法**：`model_for_task()` / `temperature_for_task()` / `max_tokens_for_task()` 模式，用 task_name 映射不同配置。
6. **`extra="ignore"`**：忽略未定义的 env var，避免因多余环境变量导致启动失败。

## 服务中使用 Settings

```python
from backend.config.settings import get_settings

class MyService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
```

允许依赖注入（测试时传入 mock Settings），也支持零配置使用（自动获取单例）。

## 新增配置字段 Checklist

1. 在 `Settings` 类中按业务域添加字段，带类型注解和默认值。
2. 如果是敏感信息，不给默认值。
3. 在 `.env.example` 中添加对应的配置说明（**不要写真实 key**）。
4. 在 `docker-compose.yml` 的 `environment` 或 `env_file` 中确保容器能读到该变量。
5. 如果字段影响缓存 key，确保加入了 `cache_digest()` 的输入。
