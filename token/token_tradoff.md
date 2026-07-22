# Token 成本优化与权衡

## 成本失控是怎么发生的

大多数团队在项目初期都是这么做的：找一个"最好"的模型，把它用在所有场景。这没什么问题——快速验证阶段合理。
但当调用量上来之后，问题就出现了：

- 一个简单的"帮我把这段文字翻译成英文"请求，和一个"分析这份财报并给出投资建议"请求，调用的是同一个高价模型
- System prompt 里堆了几百 token 的"角色设定"，每次请求都要带着
- 同样的问题被不同用户问了上百次，每次都消耗真实 token

这三个问题叠加，足以让成本比"理论最低值"高出 3-5 倍。

## Token 计费原理回顾

大模型 API 按 token 计费，分输入（Prompt Tokens）和输出（Completion Tokens）两部分，输出通常比输入贵 2-4 倍。

```text
总费用 = 输入 token 数 × 输入单价 + 输出 token 数 × 输出单价
```

token 与字符的对应关系大致是：

- 英文：1 token ≈ 4 个字符
- 中文：1 token ≈ 1-2 个汉字（因模型分词器不同而异）

所以一个包含 500 字中文的 system prompt，大约消耗 300-500 个 token，每次请求都要带上，日均 10 万次调用意味着这 500 字每天被"读"了 10 万遍。

## 国产模型定价对比（2024 年参考）

| 模型 | 输入价格（元/百万 token） | 输出价格（元/百万 token） | 适用场景 |
| --- | ---: | ---: | --- |
| DeepSeek V3 | 1 | 4 | 通用推理、代码、中文理解 |
| DeepSeek R1 | 4 | 16 | 复杂推理、数学、深度分析 |
| Qwen-Turbo | 0.3 | 0.6 | 简单任务、高频低复杂度 |
| Qwen-Plus | 0.8 | 2 | 中等复杂度通用任务 |
| Qwen-Max | 2.4 | 9.6 | 复杂任务、长上下文 |
| GLM-4-Flash | 0.1 | 0.1 | 极简任务、分类、提取 |
| GLM-4 | 0.1（128k 以内） | 0.1 | 通用对话 |
| Moonshot v1-8k | 12 | 12 | 长文本理解（8k 窗口） |

注：以上价格为写作时参考，实际以各厂商官网为准。各厂商均有不同档位折扣。

定价差距非常显著：最贵和最便宜的模型之间，同等 token 量的费用相差可达 100 倍以上。这意味着选对模型是最大的杠杆。

## 策略 1：选对模型——让任务和模型的能力匹配

这是成本优化中回报最高的一步，也最容易被忽视。

任务分级框架：

```text
Level 1 - 结构化提取/分类（GLM-4-Flash、Qwen-Turbo）
  ├─ 从文本中提取关键字
  ├─ 情感分类（正面/负面/中性）
  └─ 格式转换（JSON ↔ 文本）

Level 2 - 通用生成/对话（DeepSeek V3、Qwen-Plus）
  ├─ 普通问答
  ├─ 文案生成
  └─ 代码补全（中等复杂度）

Level 3 - 深度推理（DeepSeek R1、Qwen-Max）
  ├─ 复杂逻辑分析
  ├─ 数学证明
  └─ 多步骤规划
```

一个真实案例：某客服系统把所有请求路由到 Qwen-Max，优化后将"意图识别"步骤改用 GLM-4-Flash，只在需要生成回复时才调用 Qwen-Plus。结果：同等效果下，成本下降约 55%。

## 策略 2：精简 Prompt——每节省 100 token，日均 10 万次调用省 ¥3,650/年

### System Prompt 审计

把你的 system prompt 贴出来问一下："哪些句子如果删掉，模型表现不会变差？"
常见的冗余内容：

- 过度解释的角色设定（"你是一个有着丰富经验的、专业的……"）
- 重复的约束（同一条规则用三种方式说了三遍）
- 示例过多（Few-shot 示例确实有效，但 3 个和 10 个的差距通常很小）

量化验证方法：

```python
import tiktoken

def count_tokens(text: str, model: str = "gpt-3.5-turbo") -> int:
    """估算 token 数量（适用于大多数基于 BPE 的模型）"""
    enc = tiktoken.encoding_for_model(model)
    return len(enc.encode(text))

# 对比优化前后
original_prompt = "你是一个专业的、经验丰富的客服助手，你的职责是..."
optimized_prompt = "你是客服助手，负责..."

print(f"原始: {count_tokens(original_prompt)} tokens")
print(f"优化后: {count_tokens(optimized_prompt)} tokens")
print(f"节省: {count_tokens(original_prompt) - count_tokens(optimized_prompt)} tokens")
```

### Few-shot 示例压缩技巧

原始写法（每个示例都有完整的上下文和解释）：

```text
示例1：用户说"我想买手机"，这表明用户有购买意向，你应该推荐产品...
示例2：用户说"这个太贵了"，这表明用户对价格不满意，你应该介绍优惠...
```

压缩写法（表格或 JSON 格式）：

```json
[{"input":"我想买手机","intent":"purchase"},{"input":"太贵了","intent":"price_objection"}]
```

相同信息量，token 减少约 40%。

## 策略 3：智能路由——根据任务复杂度自动切换模型

在路由层加入一个"复杂度评估"步骤，根据请求特征动态选择模型。

```python
from dataclasses import dataclass
from enum import Enum

class TaskComplexity(Enum):
    SIMPLE = "simple"      # 分类、提取、简短问答
    MEDIUM = "medium"      # 通用生成、代码补全
    COMPLEX = "complex"    # 深度推理、长文档分析

MODEL_MAP = {
    TaskComplexity.SIMPLE:  "glm-4-flash",
    TaskComplexity.MEDIUM:  "deepseek-chat",    # DeepSeek V3
    TaskComplexity.COMPLEX: "deepseek-reasoner", # DeepSeek R1
}

def estimate_complexity(messages: list[dict]) -> TaskComplexity:
    """基于启发式规则快速评估任务复杂度"""
    last_user_msg = next(
        (m["content"] for m in reversed(messages) if m["role"] == "user"),
        ""
    )

    # 长文本通常意味着更复杂的任务
    if len(last_user_msg) > 500:
        return TaskComplexity.COMPLEX

    # 推理类关键词
    reasoning_keywords = ["分析", "推导", "证明", "为什么", "比较", "评估", "规划"]
    if any(kw in last_user_msg for kw in reasoning_keywords):
        return TaskComplexity.COMPLEX

    # 简单结构化任务
    simple_keywords = ["翻译", "提取", "分类", "总结", "转换", "是否"]
    if any(kw in last_user_msg for kw in simple_keywords) and len(last_user_msg) < 200:
        return TaskComplexity.SIMPLE

    return TaskComplexity.MEDIUM

def smart_route(messages: list[dict], force_model: str = None) -> str:
    """智能路由：返回应使用的模型名"""
    if force_model:
        return force_model

    complexity = estimate_complexity(messages)
    return MODEL_MAP[complexity]

# 使用示例
messages = [{"role": "user", "content": "把'早上好'翻译成英文"}]
model = smart_route(messages)
print(model)  # → glm-4-flash
```

这个启发式方案很粗糙，但实践中效果出奇地好——大多数业务场景的任务分布是高度偏斜的（70-80% 都是简单任务），只要把这部分流量切到便宜模型，成本就会大幅下降。
更进阶的做法是训练一个轻量级分类器（甚至用规则引擎），对任务类型做更精准的判断。如果不想自己维护路由基础设施，笔者开发的 TheRouter 在网关层内置了多模型路由和用量分析，Dashboard 提供可视化的成本趋势，可以直接接入替代本节的自建方案。

## 策略 4：语义缓存——相似问题不重复消耗

普通缓存（精确匹配）对 AI 场景效果有限，因为用户几乎不会问完全一样的问题。语义缓存解决这个问题：把"你好"和"您好啊"识别为相同查询。

核心思路：

- 请求进来时，用 Embedding 模型把问题向量化
- 在向量数据库中搜索相似的历史问题（余弦相似度 > 阈值）
- 命中则直接返回缓存结果，不调用生成模型

```python
import redis
import numpy as np
import json
from typing import Optional

class SemanticCache:
    def __init__(self, redis_client: redis.Redis, similarity_threshold: float = 0.92):
        self.redis = redis_client
        self.threshold = similarity_threshold
        self.cache_prefix = "semantic_cache:"
        self.ttl = 3600 * 24  # 24小时过期

    def get_embedding(self, text: str) -> list[float]:
        """调用 Embedding 模型获取向量（示例用 Qwen embedding）"""
        # 实际替换为你使用的 embedding API
        raise NotImplementedError("请替换为实际 embedding 调用")

    def cosine_similarity(self, a: list[float], b: list[float]) -> float:
        a, b = np.array(a), np.array(b)
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

    def get(self, question: str) -> Optional[str]:
        """查找语义相似的缓存结果"""
        query_vec = self.get_embedding(question)

        # 遍历缓存条目（生产环境应用向量数据库如 Milvus/Qdrant）
        for key in self.redis.scan_iter(f"{self.cache_prefix}*"):
            entry = json.loads(self.redis.get(key))
            similarity = self.cosine_similarity(query_vec, entry["embedding"])
            if similarity >= self.threshold:
                return entry["response"]

        return None

    def set(self, question: str, response: str) -> None:
        """存入缓存"""
        embedding = self.get_embedding(question)
        cache_key = f"{self.cache_prefix}{hash(question)}"
        self.redis.setex(
            cache_key,
            self.ttl,
            json.dumps({"question": question, "embedding": embedding, "response": response})
        )

# 在请求处理流程中接入缓存
async def handle_request(messages: list[dict]) -> str:
    last_question = messages[-1]["content"]

    # 先查缓存
    cached = semantic_cache.get(last_question)
    if cached:
        metrics.increment("cache_hit")
        return cached

    # 缓存未命中，调用模型
    response = await call_llm(messages)

    # 存入缓存
    semantic_cache.set(last_question, response)
    return response
```

注意事项：

- 相似度阈值要根据业务调整。客服场景可以设到 0.95（宁可不命中也不返回错误答案），内容生成场景可以放宽到 0.88。
- Embedding 本身也有成本，但比生成模型便宜 10-50 倍，只要缓存命中率超过 5%，就值得做。
- 不是所有请求都适合缓存——带有时间敏感信息（"今天天气怎么样"）或用户个人上下文的请求应跳过缓存。

## 策略 5：控制输出——max_tokens、stop 序列和 temperature

### max_tokens 精细化

很多代码里写的是 max_tokens: 4096 或者干脆不设，让模型自由发挥。实际上，不同场景对输出长度的需求差异很大：

```python
MAX_TOKENS_BY_TASK = {
    "sentiment_analysis": 10,      # 只需要"正面/负面/中性"
    "keyword_extraction": 50,
    "short_answer": 200,
    "content_generation": 800,
    "document_analysis": 2000,
}
```

输出 token 通常是输入的 2-4 倍贵，精确控制 max_tokens 收益显著。

### Stop 序列

当你知道模型应该在什么地方停止时，设置 stop 序列可以避免无效输出：

```python
# 生成 JSON 时，遇到结束的 } 就停止（配合 max_tokens 双保险）
response = client.chat.completions.create(
    model="deepseek-chat",
    messages=messages,
    max_tokens=500,
    stop=["```", "\n\n\n"],  # 代码块结束或三个换行时停止
)
```

### Temperature

低温度（0.1-0.3）使输出更确定性，同时减少模型"废话"的概率。对于结构化输出任务（JSON 提取、分类），温度设为 0 几乎总是正确选择。

## 实际案例：月费 ¥20,000 → ¥8,000

某内容平台场景，日均 10 万次调用，初始架构：全部流量用 Qwen-Max。
优化过程：

| 优化步骤 | 措施 | 节省比例 |
| --- | --- | ---: |
| 任务分级 | 40% 的简单任务切到 GLM-4-Flash | 35% |
| 语义缓存 | 命中率约 18%（重复类问题多） | 15% |
| Prompt 精简 | System prompt 从 800 token 压到 200 token | 8% |
| max_tokens 优化 | 按任务类型设置上限 | 5% |

累计节省约 60%，月费从 ¥20,000 降至 ¥8,000。

## 费用追踪封装器（Python）

把成本追踪嵌入调用层，实时掌握每个功能模块的 API 开销：

```python
import time
from dataclasses import dataclass, field
from contextlib import contextmanager
from typing import Generator

# 各模型单价（元/百万token）
PRICING = {
    "deepseek-chat":      {"input": 1.0,  "output": 4.0},
    "deepseek-reasoner":  {"input": 4.0,  "output": 16.0},
    "qwen-turbo":         {"input": 0.3,  "output": 0.6},
    "qwen-plus":          {"input": 0.8,  "output": 2.0},
    "qwen-max":           {"input": 2.4,  "output": 9.6},
    "glm-4":              {"input": 0.1,  "output": 0.1},
}

@dataclass
class CostRecord:
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    feature: str = "unknown"

    @property
    def cost_yuan(self) -> float:
        price = PRICING.get(self.model, {"input": 0, "output": 0})
        return (
            self.prompt_tokens / 1_000_000 * price["input"] +
            self.completion_tokens / 1_000_000 * price["output"]
        )

    def __str__(self) -> str:
        return (
            f"[{self.feature}] {self.model} | "
            f"in={self.prompt_tokens} out={self.completion_tokens} | "
            f"¥{self.cost_yuan:.6f} | {self.latency_ms:.0f}ms"
        )

class CostTracker:
    def __init__(self):
        self.records: list[CostRecord] = []

    def record(self, record: CostRecord):
        self.records.append(record)
        print(record)  # 开发阶段实时输出，生产环境改为写日志

    def summary(self) -> dict:
        by_feature: dict[str, float] = {}
        for r in self.records:
            by_feature[r.feature] = by_feature.get(r.feature, 0) + r.cost_yuan
        return {
            "total_cost": sum(r.cost_yuan for r in self.records),
            "total_calls": len(self.records),
            "by_feature": by_feature,
        }

tracker = CostTracker()

def tracked_llm_call(
    client,
    model: str,
    messages: list[dict],
    feature: str = "unknown",
    **kwargs
) -> str:
    """带成本追踪的 LLM 调用封装"""
    start = time.time()

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        **kwargs
    )

    latency_ms = (time.time() - start) * 1000
    usage = response.usage

    tracker.record(CostRecord(
        model=model,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        latency_ms=latency_ms,
        feature=feature,
    ))

    return response.choices[0].message.content

# 使用示例
result = tracked_llm_call(
    client=your_client,
    model="deepseek-chat",
    messages=[{"role": "user", "content": "用一句话介绍人工智能"}],
    feature="homepage_intro",
    max_tokens=100,
)

# 查看汇总
print(tracker.summary())
# → {'total_cost': 0.000023, 'total_calls': 1, 'by_feature': {'homepage_intro': 0.000023}}
```

## 小结

五条策略的优先级和难度排序：

| 策略 | 预期收益 | 实现难度 | 优先级 |
| --- | ---: | --- | --- |
| 选对模型 | 30-50% | 低 | P0 |
| 精简 Prompt | 5-15% | 低 | P0 |
| 语义缓存 | 10-30% | 中 | P1 |
| 智能路由 | 10-20% | 中 | P1 |
| 控制输出 | 5-10% | 低 | P2 |

**建议执行顺序：** 先做"选对模型"和"精简 Prompt"（改动小、见效快），再建语义缓存（需要基础设施投入，但命中率高的场景回报极高），最后精细化路由和输出控制。

成本优化本质上是一个持续迭代的过程——每隔一段时间看一次 tracker.summary()，找到成本最高的功能模块，专项优化，效果比一开始就想做大而全的方案要好得多。
