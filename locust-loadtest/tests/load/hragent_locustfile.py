# ============================================================================
# HRagent-05 Locust 压力测试/负载测试 入口文件
# ============================================================================
"""
HRagent-05 Locust load test file.
本文件定义了 Locust 负载测试的全部行为，包括用户登录、GET/POST 接口压测、
以及基于环境变量的 CI/CD 质量门禁检查。

用法示例 (Usage):
  locust -f locust-loadtest/tests/load/hragent_locustfile.py \
    -H http://localhost:8111 \
    --headless -u 1 -r 1 -t 10s \
    --html reports/hragent_smoke_1u.html \
    --csv reports/hragent_smoke_1u \
    --csv-full-history \
    --json-file reports/hragent_smoke_1u.json

参数说明:
  -H HOST            被测服务的基础地址（如 http://localhost:8111）
  --headless          无界面模式（CI/CD 中必须使用）
  -u USERS            并发虚拟用户数
  -r SPAWN_RATE       每秒启动的用户数（爬坡速率）
  -t RUN_TIME         测试持续时间（如 10s / 5m / 1h）
  --html PATH         测试结束后生成 HTML 报告
  --csv PATH          统计数据的 CSV 前缀
  --csv-full-history  每一秒写入一次统计（便于事后分析趋势）
  --json-file PATH    测试结束后写入 JSON 摘要

环境变量说明 (Environment variables):
  HRAGENT_EMAIL                     登录邮箱，默认: aah5sgh@bosch.com
  HRAGENT_PASSWORD                  登录密码，当认证启用时必须提供
  HRAGENT_REGISTER_IF_MISSING       用户不存在时是否自动注册，默认: false
  HRAGENT_DISPLAY_NAME              注册时的昵称，默认: Locust User
  HRAGENT_AUTH_ENABLED              是否启用认证流程，默认: true
  HRAGENT_VERIFY_TLS                是否验证 HTTPS 证书，默认: true（自签证书可设为 false）
  HRAGENT_READ_ENDPOINTS            逗号分隔的 GET 接口列表（用于读压测）
  HRAGENT_POST_ENDPOINTS_JSON       JSON 列表，定义 POST 业务接口（用于写压测）
  HRAGENT_FLOW_MODE                  basic 或 full；full 时 1 用户只跑一次完整流程
  HRAGENT_FULL_FLOW_MESSAGES_MIN     full 模式每位用户最少预演轮数，默认: 5
  HRAGENT_FULL_FLOW_MESSAGES_MAX     full 模式每位用户最多预演轮数，默认: 10
  HRAGENT_REPORT_TIMEOUT_SECONDS     复盘 SSE 的单次空闲读取超时(秒)，默认: 600
  HRAGENT_MAX_FAIL_RATIO            质量门禁-最大失败率，默认: 0.01 (1%)
  HRAGENT_MAX_AVG_MS                质量门禁-最大平均响应时间(ms)，默认: 800
  HRAGENT_MAX_P95_MS                质量门禁-最大P95响应时间(ms)，默认: 2000
"""

from __future__ import annotations

import json
import logging
import os
import random
from itertools import count
from time import perf_counter
from http.cookies import SimpleCookie
from threading import Lock
from typing import Any

# Locust 核心模块
# HttpUser: 基于 HTTP 协议的虚拟用户基类，内部封装了 requests.Session
# between:  等待时间策略，在两个值之间随机取一个等待秒数
# events:   事件钩子系统，用于在测试生命周期的关键节点注入自定义逻辑
# task:     装饰器，将方法标记为可执行任务，数字参数表示权重（越大执行概率越高）
# StopUser: 异常类，抛出后立即终止当前虚拟用户
from locust import HttpUser, between, events, task
from locust.exception import StopUser


# 工具函数 - 环境变量解析

def env_bool(name: str, default: bool = False) -> bool:
    """
    从环境变量读取布尔值。
    支持的 true 值: "1", "true", "yes", "y", "on"（不区分大小写）
    未设置或空字符串时返回默认值。

    参数:
        name:    环境变量名
        default: 默认值
    返回:
        解析后的布尔值
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def env_float(name: str, default: float) -> float:
    """
    从环境变量读取浮点数值。
    用于 CI/CD 质量门禁阈值配置，如最大失败率、最大响应时间等。

    参数:
        name:    环境变量名
        default: 默认值
    返回:
        解析后的浮点数
    """
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def parse_read_endpoints() -> list[str]:
    """
    解析 HRAGENT_READ_ENDPOINTS 环境变量，返回 GET 接口路径列表。

    默认包含两个轻量读接口:
        - /api/v1/health     健康检查
        - /api/v1/auth/me     当前用户信息

    返回:
        去除空白后的接口路径列表
    """
    raw = os.getenv("HRAGENT_READ_ENDPOINTS", "/api/v1/health,/api/v1/auth/me")
    return [item.strip() for item in raw.split(",") if item.strip()]


def parse_post_endpoints() -> list[dict[str, Any]]:
    """
    解析 HRAGENT_POST_ENDPOINTS_JSON 环境变量，返回 POST 压测场景列表。

    JSON 格式示例:
        [
          {
            "path": "/api/v1/sessions",
            "payload": {"title": "test", "description": "load test"},
            "name": "POST /api/v1/sessions"
          }
        ]

    每个场景必须包含:
        - path:    接口路径（必填）
        - payload: 请求体 JSON 对象（选填，默认 {}）
        - name:    在 Locust 统计报表中显示的名称（选填，默认 "POST <path>"）

    返回:
        场景字典列表；未配置时返回空列表
    抛出:
        RuntimeError: JSON 格式不合法或不是列表类型
    """
    raw = os.getenv("HRAGENT_POST_ENDPOINTS_JSON", "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"HRAGENT_POST_ENDPOINTS_JSON is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise RuntimeError("HRAGENT_POST_ENDPOINTS_JSON must be a JSON list")
    return data


def locust_database_url() -> str:
    raw = os.getenv("HRAGENT_TEST_DATABASE_URL") or os.getenv("DATABASE_URL") or ""
    if raw.strip():
        return raw.strip()
    return "postgresql://hr_agent:hr_agent@localhost:5432/hr_agent"


def load_test_credentials_from_postgres() -> list[dict[str, str]]:
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError:
        logging.error("psycopg is required to load the authorized database test accounts")
        return []

    try:
        with psycopg.connect(locust_database_url(), row_factory=dict_row) as conn:
            rows = conn.execute(
                """
                SELECT credentials.email::text AS email
                FROM locust_test_credentials AS credentials
                JOIN auth_whitelist AS whitelist
                  ON lower(whitelist.email::text) = lower(credentials.email::text)
                 AND whitelist.enabled = TRUE
                JOIN app_users AS users
                  ON lower(users.email::text) = lower(credentials.email::text)
                 AND users.is_active = TRUE
                WHERE credentials.enabled = TRUE
                ORDER BY credentials.id
                """
            ).fetchall()
    except Exception as exc:  # noqa: BLE001
        logging.error("Cannot load the authorized database test accounts: %s", exc)
        return []

    shared_password = os.getenv("HRAGENT_PASSWORD", "").strip()
    if not shared_password:
        logging.error("HRAGENT_PASSWORD is required for the authorized database test accounts")
        return []

    credentials: list[dict[str, str]] = []
    for row in rows:
        email = str(row.get("email") or "").strip().lower()
        if email:
            credentials.append({"email": email, "password": shared_password})
    return credentials


# 虚拟用户类 - 模拟一个真实 HRagent 用户的行为

class HRagentUser(HttpUser):
    """
    模拟一个 HRagent 用户的生命周期：

    1. on_start 阶段（用户启动时）：
       - 读取所有环境变量配置
       - 如果启用认证：可选自动注册 + 必选登录
       - 登录成功后，后续所有请求自动携带 session cookie

    2. 运行期间（持续循环执行 task）：
       - @task(2) read_scenario:        权重 2，随机访问配置的 GET 接口
       - @task(1) business_post_scenario: 权重 1，执行配置的 POST 业务场景
       - 权重比 2:1 意味着约 67% 的请求是读操作，33% 是写操作

    3. 可通过 HRAGENT_POST_ENDPOINTS_JSON 增加真实业务 POST 场景。
    """

    # 每次任务执行后的等待时间（秒），在 1 到 3 秒之间随机取值
    # 这模拟了真实用户的操作间隔，避免请求过于密集
    wait_time = between(1, 3)
    credential_pool: list[dict[str, str]] | None = None
    credential_index = count()
    credential_lock = Lock()

    # on_start: 虚拟用户启动时执行一次，用于初始化配置和登录

    def on_start(self) -> None:
        """
        虚拟用户启动入口。
        执行顺序:
            1. 从环境变量读取所有配置
            2. 处理 TLS 证书验证设置
            3. 如果启用认证: 可选注册 → 登录
        """
        # ---- 读取配置 ----
        self.auth_enabled = env_bool("HRAGENT_AUTH_ENABLED", True)
        self.verify_tls = env_bool("HRAGENT_VERIFY_TLS", True)
        self.email = os.getenv("HRAGENT_EMAIL", "aah5sgh@bosch.com").strip().lower()
        self.password = os.getenv("HRAGENT_PASSWORD", "")
        self.display_name = os.getenv("HRAGENT_DISPLAY_NAME", "Locust User")
        self.auth_cookie_name = os.getenv("HRAGENT_AUTH_COOKIE_NAME", "hragent_session")
        self.flow_mode = os.getenv("HRAGENT_FLOW_MODE", "full").strip().lower()
        self.full_flow_done = False
        self.logged_in = False
        self.logout_done = False
        self.read_endpoints = parse_read_endpoints()
        self.post_endpoints = parse_post_endpoints()
        self._assign_test_credential()

        # 本地自签 HTTPS 证书压测时可设置 HRAGENT_VERIFY_TLS=false
        # 避免 TLS 握手失败导致大量假阳性错误
        try:
            self.client.verify = self.verify_tls
        except Exception:
            pass

        # ---- 认证流程 ----
        if self.auth_enabled:
            # 未配置密码时无法登录，直接终止用户
            if not self.password:
                logging.error("HRAGENT_PASSWORD is required when HRAGENT_AUTH_ENABLED=true")
                raise StopUser()
            # 如果配置了自动注册，先尝试注册（幂等，已存在也不报错）
            if env_bool("HRAGENT_REGISTER_IF_MISSING", False):
                self._register_once()
            # 登录获取 session cookie
            self._login()

    def on_stop(self) -> None:
        self._logout_once()

    def _logout_once(self) -> None:
        if (
            not getattr(self, "auth_enabled", False)
            or not getattr(self, "logged_in", False)
            or getattr(self, "logout_done", False)
        ):
            return
        self.logout_done = True
        with self.client.post("/api/v1/auth/logout", name="POST /api/v1/auth/logout", catch_response=True) as resp:
            if resp.status_code in {200, 204, 401}:
                resp.success()
            else:
                resp.failure(f"logout failed status={resp.status_code}, body={resp.text[:200]}")

    def _assign_test_credential(self) -> None:
        if not env_bool("HRAGENT_USE_TEST_CREDENTIAL_TABLE", True):
            return

        cls = type(self)
        with cls.credential_lock:
            if cls.credential_pool is None:
                cls.credential_pool = load_test_credentials_from_postgres()
            pool = cls.credential_pool
            if not pool:
                logging.error("No enabled Locust whitelist credentials are available")
                raise StopUser()
            credential_slot = next(cls.credential_index)
            if credential_slot >= len(pool):
                logging.error(
                    "Requested more Locust users than authorized fixed test accounts: users=%s accounts=%s",
                    credential_slot + 1,
                    len(pool),
                )
                raise StopUser()
            credential = pool[credential_slot]

        self.email = credential["email"]
        self.password = credential["password"]
        self.client.headers["X-Forwarded-For"] = (
            f"198.18.{credential_slot // 254}.{credential_slot % 254 + 1}"
        )

    # _register_once: 一次性注册（幂等操作）

    def _register_once(self) -> None:
        """
        尝试注册用户。这是一个容错设计:
        - 用户已存在 → 200/409 → 标记成功，继续登录
        - 白名单限制 → 400     → 标记成功（压测注册不是主路径）
        - 注册成功   → 201     → 标记成功
        - 其他错误   → 标记失败但不中断（仍然尝试后续登录）

        注意: 该方法使用 catch_response=True 自行判断成功/失败，
              压测注册不是压测主目标，因此采用宽松策略。
        """
        payload = {
            "email": self.email,
            "password": self.password,
            "display_name": self.display_name,
        }
        with self.client.post(
            "/api/v1/auth/register",
            json=payload,
            name="POST /api/v1/auth/register",
            catch_response=True,
        ) as resp:
            # 已存在、已注册、白名单外等场景可能返回 400/409/200。
            # 压测注册不是主路径，因此这里只记录，不中断。
            if resp.status_code in {200, 201, 400, 409}:
                resp.success()
            else:
                resp.failure(f"unexpected register status={resp.status_code}, body={resp.text[:200]}")

    # _login: 登录并获取 session cookie

    def _login(self) -> None:
        """
        登录接口调用。
        成功返回 200 后，服务端会设置 session cookie，
        后续 self.client 发出的所有请求会自动携带该 cookie。

        登录失败时直接抛出 StopUser() 终止当前虚拟用户，
        避免无认证状态的后续请求产生大量无意义的 401 错误统计。
        """
        payload = {"email": self.email, "password": self.password}
        with self.client.post(
            "/api/v1/auth/login",
            json=payload,
            name="POST /api/v1/auth/login",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                self._persist_auth_cookie_for_http(resp)
                self.logged_in = True
                resp.success()
                return
            resp.failure(f"login failed status={resp.status_code}, body={resp.text[:200]}")
            raise StopUser()

    def _persist_auth_cookie_for_http(self, resp) -> None:
        """
        HRagent 后端默认返回 Secure cookie，用于 HTTPS 前端。
        本地 Locust 常用 http://localhost:8111 压测；requests 不会在 HTTP 请求中发送 Secure cookie。
        这里仅在 Locust 测试客户端内复制 session cookie，并去掉 secure 标记。
        """
        session_id = resp.cookies.get(self.auth_cookie_name)
        if not session_id:
            raw_cookie = resp.headers.get("set-cookie", "")
            parsed = SimpleCookie()
            parsed.load(raw_cookie)
            morsel = parsed.get(self.auth_cookie_name)
            session_id = morsel.value if morsel else None
        if not session_id:
            raise StopUser()
        self.client.cookies.set(self.auth_cookie_name, session_id, path="/")


    # 压测任务 - 运行时持续循环执行

    @task(2)
    def read_scenario(self) -> None:
        if self.flow_mode == "full":
            self._run_full_flow_once()
            return
        """
        读接口压测任务 (权重 2)。

        从 self.read_endpoints 列表中随机选取一个 GET 接口，
        发送请求并根据状态码判断成功或失败:
            - 200/204 → 成功
            - 401     → 未授权（session 丢失/过期/路由未配置认证）
            - 404     → 接口不存在（检查 HRAGENT_READ_ENDPOINTS 配置）
            - 其他    → 记录异常状态码和响应体前 200 字符用于排查

        权重 2 意味着该任务执行频率是 business_post_scenario 的 2 倍。
        """
        endpoint = random.choice(self.read_endpoints)
        name = f"GET {endpoint}"
        with self.client.get(endpoint, name=name, catch_response=True) as resp:
            if resp.status_code in {200, 204}:
                resp.success()
            elif resp.status_code == 401:
                resp.failure("unauthorized: session cookie missing/expired or auth route not configured")
            elif resp.status_code == 404:
                resp.failure("endpoint not found: check HRAGENT_READ_ENDPOINTS")
            else:
                resp.failure(f"unexpected status={resp.status_code}, body={resp.text[:200]}")

    @task(1)
    def business_post_scenario(self) -> None:
        if self.flow_mode == "full":
            self._run_full_flow_once()
            return
        """
        业务 POST 接口压测任务 (权重 1)。

        行为逻辑:
            1. 如果未配置 HRAGENT_POST_ENDPOINTS_JSON:
               → 回退到 GET /api/v1/auth/me 读接口，保持轻量压测
            2. 如果已配置 POST 场景列表:
               → 随机选择一个场景，使用场景中定义的 path/payload/name 发起请求

        响应判断:
            - 2xx   → 成功
            - 401   → 未授权
            - 404   → 接口不存在
            - 其他  → 记录状态码和响应体前 300 字符
        """
        if not self.post_endpoints:
            # 没有配置真实业务 POST 时，用 /auth/me 保持轻量读压测。
            # 这是一个容错设计: 确保即使不配 POST 场景，压测也能正常运行。
            with self.client.get("/api/v1/auth/me", name="GET /api/v1/auth/me fallback", catch_response=True) as resp:
                if resp.status_code in {200, 204}:
                    resp.success()
                elif not self.auth_enabled and resp.status_code in {401, 404}:
                    # 未启用认证时，401/404 是预期行为
                    resp.success()
                else:
                    resp.failure(f"unexpected fallback status={resp.status_code}")
            return

        # 从配置的 POST 场景列表中随机选取一个
        scenario = random.choice(self.post_endpoints)
        path = scenario.get("path")
        payload = scenario.get("payload", {})
        name = scenario.get("name", f"POST {path}")

        # path 是必填字段，缺失时直接报错终止
        if not path:
            raise RuntimeError("Each POST scenario must contain path")

        with self.client.post(path, json=payload, name=name, catch_response=True) as resp:
            if 200 <= resp.status_code < 300:
                resp.success()
            elif resp.status_code == 401:
                resp.failure("unauthorized: session cookie missing/expired")
            elif resp.status_code == 404:
                resp.failure("endpoint not found: check HRAGENT_POST_ENDPOINTS_JSON")
            else:
                resp.failure(f"unexpected status={resp.status_code}, body={resp.text[:300]}")


    def _run_full_flow_once(self) -> None:
        """Run one complete HRagent business flow per virtual user."""
        if self.full_flow_done:
            return
        self.full_flow_done = True
        try:
            session = self._post_json("/api/v1/sessions", {}, "POST /api/v1/sessions")
            session_id = str(session.get("session_id") or "")
            if not session_id:
                raise RuntimeError("create session response missing session_id")

            self._get_json("/api/v1/employees?q=locust&limit=1", "GET /api/v1/employees search")
            self._post_document_text(
                session_id=session_id,
                filename="locust_employee_profile.txt",
                text=self._load_test_profile_text(),
            )

            profile = self._load_test_profile()
            self._patch_json(
                f"/api/v1/setup/{session_id}/profile",
                {"profile": profile},
                "PATCH /api/v1/setup/[session]/profile",
            )
            options = self._get_json("/api/v1/setup/options", "GET /api/v1/setup/options")
            intent_id = self._select_intent_id(options)
            self._patch_json(
                f"/api/v1/setup/{session_id}/intent",
                {"intent_id": intent_id, "free_text": None},
                "PATCH /api/v1/setup/[session]/intent",
            )
            personality, primary_motive_id, secondary_motive_ids = self._select_simulation_options(
                options,
                intent_id,
            )
            self._patch_json(
                f"/api/v1/setup/{session_id}/simulation",
                {
                    "personality": personality,
                    "primary_motive_id": primary_motive_id,
                    "secondary_motive_ids": secondary_motive_ids,
                    "run_mode": "guidance_then_rehearsal",
                },
                "PATCH /api/v1/setup/[session]/simulation",
            )
            self._post_json(f"/api/v1/setup/{session_id}/complete", {}, "POST /api/v1/setup/[session]/complete")
            self._post_guidance_stream(session_id)
            messages = self._load_test_messages()
            min_turns = max(1, env_int("HRAGENT_FULL_FLOW_MESSAGES_MIN", 5))
            max_turns = max(min_turns, env_int("HRAGENT_FULL_FLOW_MESSAGES_MAX", 10))
            turn_count = min(len(messages), random.randint(min_turns, max_turns))
            for message in messages[:turn_count]:
                self._post_json(
                    f"/api/v1/rehearsal/{session_id}/message",
                    {
                        "message": message,
                        "input_mode": "text",
                        "audio_emotion": None,
                    },
                    "POST /api/v1/rehearsal/[session]/message",
                )
            self._post_json(f"/api/v1/rehearsal/{session_id}/end", {}, "POST /api/v1/rehearsal/[session]/end")
            self._post_coach_report_stream(session_id)
            self._get_json(f"/api/v1/sessions/{session_id}", "GET /api/v1/sessions/[session]")
        finally:
            self._logout_once()
            runner = getattr(self.environment, "runner", None)
            if runner is not None and runner.user_count <= 1:
                runner.quit()
        raise StopUser()

    def _get_json(self, path: str, name: str) -> dict[str, Any]:
        with self.client.get(path, name=name, catch_response=True) as resp:
            return self._json_or_fail(resp, name)

    def _post_json(self, path: str, payload: dict[str, Any], name: str) -> dict[str, Any]:
        with self.client.post(path, json=payload, name=name, catch_response=True) as resp:
            return self._json_or_fail(resp, name)

    def _patch_json(self, path: str, payload: dict[str, Any], name: str) -> dict[str, Any]:
        with self.client.patch(path, json=payload, name=name, catch_response=True) as resp:
            return self._json_or_fail(resp, name)

    def _post_document_text(self, session_id: str, filename: str, text: str) -> dict[str, Any]:
        payload = {"session_id": session_id, "filename": filename, "text": text}
        name = "POST /api/v1/documents/text"
        with self.client.post("/api/v1/documents/text", json=payload, name=name, catch_response=True) as resp:
            if 200 <= resp.status_code < 300:
                return self._json_or_fail(resp, name)

            body = resp.text[:500] if hasattr(resp, "text") else ""
            resp.failure(f"{name} failed status={resp.status_code}, body={body}")
            raise StopUser()

    def _post_guidance_stream(self, session_id: str) -> dict[str, Any]:
        name = "POST /api/v1/guidance/[session]/stream"
        path = f"/api/v1/guidance/{session_id}/stream"
        with self.client.post(path, json={}, name=name, stream=True, timeout=(5, 180), catch_response=True) as resp:
            if resp.status_code != 200:
                body = resp.text[:500] if hasattr(resp, "text") else ""
                resp.failure(f"{name} failed status={resp.status_code}, body={body}")
                raise StopUser()

            event_name = "message"
            done_payload: dict[str, Any] | None = None
            for raw_line in resp.iter_lines(decode_unicode=True):
                if raw_line is None:
                    continue
                line = raw_line.strip()
                if not line:
                    continue
                if line.startswith("event:"):
                    event_name = line.split(":", 1)[1].strip() or "message"
                    continue
                if not line.startswith("data:"):
                    continue

                payload_text = line.split(":", 1)[1].strip()
                try:
                    payload = json.loads(payload_text) if payload_text else {}
                except json.JSONDecodeError:
                    payload = {"raw": payload_text}

                if event_name == "error":
                    resp.failure(f"{name} stream error: {payload}")
                    raise StopUser()
                if event_name == "done":
                    done_payload = payload if isinstance(payload, dict) else {"data": payload}
                    break

            if done_payload is None:
                resp.failure(f"{name} ended without done event")
                raise StopUser()
            resp.success()
            return done_payload

    def _post_coach_report_stream(self, session_id: str) -> dict[str, Any]:
        path = f"/api/v1/reports/{session_id}/coach/stream"
        name = "POST /api/v1/reports/[session]/coach/stream"
        # This is an SSE idle-read timeout, not a target response-time objective.
        # A report may wait behind the backend's per-worker report gate.
        timeout_seconds = max(30, env_int("HRAGENT_REPORT_TIMEOUT_SECONDS", 600))
        started_at = perf_counter()
        with self.client.post(path, json={}, name=name, stream=True, timeout=(5, timeout_seconds), catch_response=True) as resp:
            if resp.status_code != 200:
                body = resp.text[:500] if hasattr(resp, "text") else ""
                resp.failure(f"{name} failed status={resp.status_code}, body={body}")
                raise StopUser()

            event_name = "message"
            done_payload: dict[str, Any] | None = None
            for raw_line in resp.iter_lines(decode_unicode=True, chunk_size=1):
                if raw_line is None:
                    continue
                line = raw_line.strip()
                if not line:
                    continue
                if line.startswith("event:"):
                    event_name = line.split(":", 1)[1].strip() or "message"
                    continue
                if not line.startswith("data:"):
                    continue

                payload_text = line.split(":", 1)[1].strip()
                try:
                    payload = json.loads(payload_text) if payload_text else {}
                except json.JSONDecodeError:
                    payload = {"raw": payload_text}
                if event_name == "error":
                    resp.failure(f"{name} stream error: {payload}")
                    raise StopUser()
                if event_name == "done":
                    done_payload = payload if isinstance(payload, dict) else {"data": payload}
                    break

            if done_payload is None:
                resp.failure(f"{name} ended without done event")
                raise StopUser()

            # stream=True otherwise measures only time to the SSE response headers.
            resp.request_meta["response_time"] = int((perf_counter() - started_at) * 1000)
            resp.success()
            return done_payload

    def _try_get_coach_report(self, path: str) -> dict[str, Any] | None:
        with self.client.get(path, name="GET /api/v1/reports/[session]/coach", timeout=(5, 30), catch_response=True) as resp:
            if 200 <= resp.status_code < 300:
                return self._json_or_fail(resp, "GET /api/v1/reports/[session]/coach")
            if resp.status_code == 404:
                resp.success()
                return None
            body = resp.text[:500] if hasattr(resp, "text") else ""
            resp.failure(f"GET /api/v1/reports/[session]/coach failed status={resp.status_code}, body={body}")
            raise StopUser()


    @staticmethod
    def _json_or_fail(resp, name: str) -> dict[str, Any]:
        if 200 <= resp.status_code < 300:
            resp.success()
            try:
                data = resp.json()
            except ValueError:
                return {}
            return data if isinstance(data, dict) else {"data": data}
        body = resp.text[:500] if hasattr(resp, "text") else ""
        resp.failure(f"{name} failed status={resp.status_code}, body={body}")
        raise StopUser()

    @staticmethod
    def _select_intent_id(options: dict[str, Any]) -> str:
        default_id = options.get("default_intent")
        if default_id:
            return str(default_id)
        intents = options.get("intents") or []
        if not intents:
            raise RuntimeError("setup options missing intents")
        return str(intents[0]["id"])

    @staticmethod
    def _select_simulation_options(options: dict[str, Any], intent_id: str) -> tuple[dict[str, int], str, list[str]]:
        default_personality = options.get("default_big_five") or {}
        personality = {
            key: int(default_personality.get(key, 50))
            for key in ("openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism")
        }
        motive_ids = [str(item.get("id") or "") for item in options.get("motives") or []]
        motive_ids = [motive_id for motive_id in motive_ids if motive_id]
        if len(motive_ids) < 3:
            raise RuntimeError("setup options must include at least three motives")

        recommendations = options.get("motive_recommendations") or {}
        recommendation = recommendations.get(intent_id) or options.get("default_motive_recommendation") or {}
        primary_motive_id = str(recommendation.get("primary_motive_id") or "")
        secondary_motive_ids = [
            str(motive_id)
            for motive_id in recommendation.get("secondary_motive_ids") or []
            if str(motive_id) in motive_ids and str(motive_id) != primary_motive_id
        ]
        if primary_motive_id not in motive_ids:
            primary_motive_id = motive_ids[0]
        if len(secondary_motive_ids) != 2 or len(set(secondary_motive_ids)) != 2:
            secondary_motive_ids = [motive_id for motive_id in motive_ids if motive_id != primary_motive_id][:2]
        return personality, primary_motive_id, secondary_motive_ids

    @staticmethod
    def _load_test_profile() -> dict[str, Any]:
        return {
            "employee_alias": "Ms. Locust Test",
            "role": "Project Manager",
            "department": "HSE / Load Test",
            "level": "G7",
            "reporting_line": "Test Manager",
            "performance_rating": "部分达成",
            "review_cycle": "2026 年度绩效周期",
            "conversation_topic": "改进型绩效反馈",
            "key_goals": [
                "提升项目交付准时率",
                "减少跨部门沟通返工",
                "形成可跟踪的改进行动计划",
            ],
            "facts": [
                {
                    "description": "最近两个项目里程碑均出现延期，主要集中在风险提前识别和跨部门确认环节。",
                    "impact": "影响团队交付节奏，并增加经理协调成本。",
                    "evidence_source": "locust_load_test_profile",
                },
                {
                    "description": "员工在问题复盘中愿意配合，但对评价结论较敏感。",
                    "impact": "沟通需要先确认事实，再邀请员工共同补充视角。",
                    "evidence_source": "locust_load_test_profile",
                },
            ],
            "past_ratings": ["2025: 达成"],
            "historical_feedback": ["需要更早同步项目风险和资源缺口。"],
            "previous_improvement_discussion": "yes",
            "management_actions": ["建立双周风险检查点", "明确下一阶段交付验收标准"],
            "has_pip": "no",
            "involves_promotion_salary_transfer": "no",
            "employee_status_summary": "员工整体愿意沟通，但对绩效评级和资源约束存在压力。",
            "sensitive_constraints": {
                "hr_legal": {
                    "status": "yes",
                    "business_impact_summary": "沟通中避免承诺无法兑现的晋升、薪酬或岗位变化。",
                }
            },
            "source_profile_text": "Locust full-flow smoke employee profile.",
            "extraction_notes": ["Locust 1-user full-flow smoke profile."],
        }

    @staticmethod
    def _load_test_profile_text() -> str:
        profile = HRagentUser._load_test_profile()
        profile.pop("source_profile_text", None)
        return json.dumps(profile, ensure_ascii=False, indent=2)

    @staticmethod
    def _load_test_messages() -> list[str]:
        return [
            "我们今天先对齐今年绩效事实，再一起确认后续改进计划。",
            "最近两个项目的里程碑都有延期，你怎么看主要原因？",
            "我想先听听你认为资源和跨部门协作具体卡在哪里。",
            "从已有记录看，风险同步偏晚对交付产生了影响，你是否认同？",
            "下一阶段我们需要把风险识别提前，你觉得哪些动作可以先落地？",
            "我们可以设置双周检查点，并明确每个里程碑的验收标准。",
            "你需要我协调哪些资源，才能按这个节奏推进？",
            "我们把负责人、截止时间和检查节点逐项确认一下。",
            "如果过程中出现新风险，请在检查点之前主动同步。",
            "最后确认一下：我们两周后复盘第一阶段结果，可以吗？",
        ]


# 每次从 Locust Web UI 开始新测试时重新读取授权账号并重置分配位置。
@events.test_start.add_listener
def reset_authorized_test_credentials(environment, **kwargs) -> None:
    with HRagentUser.credential_lock:
        HRagentUser.credential_pool = None
        HRagentUser.credential_index = count()

    uses_fixed_credentials = env_bool("HRAGENT_USE_TEST_CREDENTIAL_TABLE", True)
    auth_enabled = env_bool("HRAGENT_AUTH_ENABLED", True)
    has_password = bool(os.getenv("HRAGENT_PASSWORD", "").strip())
    if auth_enabled and uses_fixed_credentials and not has_password:
        logging.error(
            "Load test was not started: HRAGENT_PASSWORD is required for the enabled fixed test accounts. "
            "Set it in the shell that starts Locust, then start the test again."
        )
        environment.process_exit_code = 2
        environment.runner.quit()


# CI/CD 质量门禁 - 测试结束时自动执行


@events.quitting.add_listener
def on_quitting(environment, **kwargs) -> None:
    """
    Locust 测试退出事件监听器 —— 实现 CI/CD 质量门禁。

    在测试完全结束后触发，根据统计汇总数据判断测试是否通过。
    三个门禁指标（通过环境变量可配置）:
        1. 失败率      > HRAGENT_MAX_FAIL_RATIO (默认 1%)    → 测试失败
        2. 平均响应时间 > HRAGENT_MAX_AVG_MS     (默认 800ms) → 测试失败
        3. P95 响应时间 > HRAGENT_MAX_P95_MS     (默认 2000ms)→ 测试失败

    判断优先级: 失败率 > 平均响应时间 > P95
    即任一指标超标都判定为失败，且按上述顺序只报告第一个超标项。

    CI/CD 集成:
        测试通过 → process_exit_code = 0 → CI pipeline 继续
        测试失败 → process_exit_code = 1 → CI pipeline 阻断

    参数:
        environment: Locust 运行环境对象，包含 stats (统计数据)、runner 等信息
        **kwargs:    事件系统传入的额外参数（此处未使用）
    """
    # 汇总统计数据（所有用户、所有接口的聚合值）
    stats = environment.stats.total

    # 读取门禁阈值（支持环境变量动态配置）
    max_fail_ratio = env_float("HRAGENT_MAX_FAIL_RATIO", 0.01)   # 默认最大 1% 失败率
    max_avg_ms = env_float("HRAGENT_MAX_AVG_MS", 800.0)          # 默认最大 800ms 平均响应
    max_p95_ms = env_float("HRAGENT_MAX_P95_MS", 2000.0)         # 默认最大 2000ms P95

    # 计算实际统计值
    p95 = stats.get_response_time_percentile(0.95) or 0   # 95 分位响应时间
    avg = stats.avg_response_time or 0                     # 平均响应时间
    fail_ratio = stats.fail_ratio or 0                     # 请求失败率

    # 逐项判断，任一超标即退出码置 1
    if fail_ratio > max_fail_ratio:
        logging.error("Load test failed: fail_ratio %.4f > %.4f", fail_ratio, max_fail_ratio)
        environment.process_exit_code = 1
    elif avg > max_avg_ms:
        logging.error("Load test failed: avg_response_time %.2f ms > %.2f ms", avg, max_avg_ms)
        environment.process_exit_code = 1
    elif p95 > max_p95_ms:
        logging.error("Load test failed: p95 %.2f ms > %.2f ms", p95, max_p95_ms)
        environment.process_exit_code = 1
    else:
        # 所有指标均达标，测试通过
        logging.info("Load test passed: fail_ratio=%.4f avg=%.2fms p95=%.2fms", fail_ratio, avg, p95)
        environment.process_exit_code = 0
