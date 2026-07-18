from __future__ import annotations

import asyncio
import json
from typing import Any

from app.agents.base import DiagnosisAgent
from app.schemas import AlertCreate, DiagnosisDecision


class ClaudeAgentUnavailableError(RuntimeError):
    pass


class ClaudeDiagnosisAgent(DiagnosisAgent):
    """仅用于故障诊断和修复规划的 Claude Agent SDK 适配器。

    该 Agent 不拥有 Shell 或文件系统工具；所有运行时变更都必须经过
    服务端策略引擎和执行器。
    """

    def __init__(self, model: str, max_turns: int = 3, timeout_seconds: int = 90) -> None:
        self.model = model
        self.max_turns = max_turns
        self.timeout_seconds = timeout_seconds

    async def diagnose(
        self, alert: AlertCreate, evidence: dict[str, Any]
    ) -> DiagnosisDecision:
        try:
            from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query
        except ImportError as exc:
            raise ClaudeAgentUnavailableError(
                "未安装 claude-agent-sdk。请安装项目依赖，或使用 AI_PROVIDER=rules。"
            ) from exc

        schema = DiagnosisDecision.model_json_schema()
        prompt = (
            "请诊断这起服务故障，只能使用后端提供的证据。"
            "必须从 Schema 中选择且只选择一个 recommended_action，不得声称任何操作已经执行。\n"
            "action_parameters 必须严格遵守以下格式：\n"
            "- restart_service: 只能返回 {\"service_name\": 告警中的服务名}\n"
            "- rollback_deployment: 只能返回 {\"service_name\": 告警中的服务名, "
            "\"target_version\": \"v1-stable\"}\n"
            "- no_safe_action: 必须返回 {}\n"
            "不要返回 container_id、image、container_name、network、port 或任何其他参数。\n\n"
            f"告警信息：\n{json.dumps(alert.model_dump(mode='json'), ensure_ascii=False)}\n\n"
            f"运行证据：\n{json.dumps(evidence, ensure_ascii=False)}"
        )
        options = ClaudeAgentOptions(
            model=self.model,
            system_prompt=(
                "你是安全受控后端中的故障诊断组件。"
                "你负责分析证据并返回结构化建议，绝不能直接执行修复操作。"
            ),
            tools=[],
            allowed_tools=[],
            disallowed_tools=[
                "Bash",
                "Read",
                "Write",
                "Edit",
                "Glob",
                "Grep",
                "WebFetch",
                "WebSearch",
            ],
            setting_sources=[],
            strict_mcp_config=True,
            mcp_servers={},
            max_turns=self.max_turns,
            output_format={"type": "json_schema", "schema": schema},
        )

        structured: Any = None
        raw: str | None = None
        try:
            async with asyncio.timeout(self.timeout_seconds):
                async for message in query(prompt=prompt, options=options):
                    if isinstance(message, ResultMessage):
                        structured = message.structured_output
                        raw = message.result
        except TimeoutError as exc:
            raise ClaudeAgentUnavailableError("Claude 故障诊断超时。") from exc
        except Exception as exc:  # noqa: BLE001
            raise ClaudeAgentUnavailableError(f"Claude 故障诊断失败：{exc}") from exc

        if isinstance(structured, dict):
            return DiagnosisDecision.model_validate(structured)
        if raw:
            try:
                return DiagnosisDecision.model_validate_json(raw)
            except Exception as exc:  # noqa: BLE001
                raise ClaudeAgentUnavailableError("Claude 返回的结构化诊断结果无效。") from exc
        raise ClaudeAgentUnavailableError("Claude 未返回故障诊断结果。")