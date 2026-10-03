"""Global "Agent model context" consent shapes (D-034 §6.2, default OFF).

Mirrors the M3 grounding-consent pattern: opting in must echo the CURRENT
``CONSENT_TEXT_VERSION`` so a text update forces re-confirmation. The text
covers scope (CurrentState / Memory / chat history), provider retention
(``store=False`` pinned; provider-side abuse-monitoring retention), revocation
(degrade to deterministic-only on next run) and deletion (sources are deleted
by their own delete paths; the run keeps references, never originals).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

MODEL_CONTEXT_CONSENT_TEXT_VERSION = "v1"

MODEL_CONTEXT_CONSENT_TEXT = (
    "开启后，当你与 Agent 对话或由其主动工作时，系统会把为完成任务所必需的"
    "个人上下文——当前状态（CurrentState）、相关记忆（Memory）与本会话的近期"
    "消息——的最小渲染版本发送给模型供应商，用于理解与规划。系统不发送完整"
    "聊天记录、完整资料文件或任何凭据。供应商（OpenAI）默认不使用 API 输入"
    "输出训练模型；但送出的文本在供应商侧存在至多 30 天的滥用监控日志保留"
    "（其政策承诺默认不用于训练）。关闭本开关后，新的 Agent 运行不再向供应商"
    "发送任何个人上下文，并自动降级为仅使用本地确定性规划（计划与重排建议"
    "仍然可用）。历史运行只保留引用与校验和，不保留原文，可随来源一并删除。"
)


class ModelContextConsentRead(BaseModel):
    enabled: bool
    consent_text: str
    consent_text_version: str
    consented_at: datetime | None


class ModelContextConsentUpdate(BaseModel):
    enabled: bool
    # Version of the text the user read and agreed to; must match the current
    # MODEL_CONTEXT_CONSENT_TEXT_VERSION or the opt-in is rejected (422).
    consent_text_version: str = Field(min_length=1, max_length=32)
