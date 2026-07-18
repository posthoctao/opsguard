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

    def __init__(
        self,
        model: str,
        max_turns: int = 3,
        timeout_seconds: int = 90,
    ) -> None:
        self.model = model
        self.max_turns = max_turns
        self.timeout_seconds = timeout_seconds

    async def diagnose(
        self,
        alert: AlertCreate,
        evidence: dict[str, Any],
    ) -> DiagnosisDecision:
        try:
            from claude_agent_sdk import (
                ClaudeAgentOptions,
                ResultMessage,
                query,
            )
        except ImportError as exc:
            raise ClaudeAgentUnavailableError(
                "未安装 claude-agent-sdk。"
                "请安装项目依赖，或使用 AI_PROVIDER=rules。"
            ) from exc

        schema = DiagnosisDecision.model_json_schema()

        alert_json = json.dumps(
            alert.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        )
        evidence_json = json.dumps(
            evidence,
            ensure_ascii=False,
            indent=2,
        )

        prompt = f"""
请诊断这起服务故障，只能根据下面提供的告警信息和运行证据进行判断。

你的职责仅限于：

1. 判断最可能的故障原因。
2. 从允许的动作中选择一个修复建议。
3. 返回符合指定 JSON Schema 的结构化结果。

你不能直接执行操作，也不能声称任何操作已经执行。

## 允许的修复动作及适用范围

### restart_service

这是低风险动作，适用于以下情况：

- 服务未运行、无法访问或健康检查失败。
- 服务运行在稳定版本，但出现明显异常延迟。
- 错误率没有显示出明确的部署回归特征。
- 证据表明故障可能来自进程内部瞬时状态、资源压力或可通过重启清除的异常。

当服务处于稳定版本、仍在运行、错误率正常或较低，但延迟显著异常时，
应优先将其视为可通过受控重启恢复的进程级故障。

参数必须且只能是：

{{"service_name": "告警中的服务名"}}

### rollback_deployment

这是高风险动作，只适用于以下情况：

- 当前运行的是新版本或非稳定版本。
- 部署之后错误率、健康状态或功能出现明显恶化。
- 证据能够将故障和最近一次部署联系起来。
- 回滚到稳定版本可以恢复服务。

参数必须且只能是：

{{
  "service_name": "告警中的服务名",
  "target_version": "v1-stable"
}}

### no_safe_action

适用于以下情况：

- 证据不足或互相矛盾。
- 服务没有明显异常。
- 当前允许的重启或回滚都不能安全解决问题。
- 故障需要数据库操作、配置修改、扩容或其他未授权操作。

参数必须是：

{{}}

## 决策要求

- 必须且只能选择一个 recommended_action。
- 不要仅仅因为无法完全证明根因，就对明显可恢复的故障选择 no_safe_action。
- 当稳定版本出现明显高延迟、服务仍在运行且没有部署回归证据时，
  应选择 restart_service。
- 只有存在明确部署回归证据时，才选择 rollback_deployment。
- 不得返回 container_id、image、container_name、network、port、
  command、shell 或任何其他未授权参数。
- 不得根据常识补充证据中不存在的事实。
- confidence 必须反映现有证据的充分程度。

## 告警信息

{alert_json}

## 运行证据

{evidence_json}
""".strip()

        options = ClaudeAgentOptions(
            model=self.model,
            system_prompt=(
                "你是安全受控后端中的故障诊断组件。"
                "你负责根据运行证据和受控运行手册生成结构化修复建议，"
                "绝不能直接执行修复操作。"
                "你需要保持安全，但不能在运行手册已经明确覆盖故障时"
                "过度使用 no_safe_action。"
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
            output_format={
                "type": "json_schema",
                "schema": schema,
            },
        )

        structured: Any = None
        raw: str | None = None

        try:
            async with asyncio.timeout(self.timeout_seconds):
                async for message in query(
                    prompt=prompt,
                    options=options,
                ):
                    if isinstance(message, ResultMessage):
                        structured = message.structured_output
                        raw = message.result

        except TimeoutError as exc:
            raise ClaudeAgentUnavailableError(
                "Claude 故障诊断超时。"
            ) from exc

        except Exception as exc:  # noqa: BLE001
            raise ClaudeAgentUnavailableError(
                f"Claude 故障诊断失败：{exc}"
            ) from exc

        if isinstance(structured, dict):
            return DiagnosisDecision.model_validate(structured)

        if raw:
            try:
                return DiagnosisDecision.model_validate_json(raw)
            except Exception as exc:  # noqa: BLE001
                raise ClaudeAgentUnavailableError(
                    "Claude 返回的结构化诊断结果无效。"
                ) from exc

        raise ClaudeAgentUnavailableError(
            "Claude 未返回故障诊断结果。"
        )
