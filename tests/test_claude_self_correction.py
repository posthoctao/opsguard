from __future__ import annotations

import asyncio
import sys
import types
from typing import Any

import pytest
from pydantic import ValidationError

from app.agents.claude import ClaudeAgentUnavailableError, ClaudeDiagnosisAgent
from app.schemas import AlertCreate, DiagnosisDecision


def _alert() -> AlertCreate:
    return AlertCreate(
        service_name="demo-api",
        alert_type="ServiceUnavailable",
        summary="服务健康检查失败",
    )


def _valid_output() -> dict[str, Any]:
    return {
        "summary": "demo-api 当前不可用。",
        "root_cause": "服务进程未运行。",
        "confidence": 0.95,
        "evidence": ["health_check=false"],
        "recommended_action": "restart_service",
        "action_parameters": {"service_name": "demo-api"},
    }


def _invalid_output() -> dict[str, Any]:
    output = _valid_output()
    output["action_parameters"] = {
        "service_name": "demo-api",
        "container_id": "hallucinated-container-id",
    }
    return output


def _install_fake_sdk(
    monkeypatch: pytest.MonkeyPatch,
    outputs: list[dict[str, Any]],
    prompts: list[str],
) -> None:
    module = types.ModuleType("claude_agent_sdk")

    class ClaudeAgentOptions:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    class ResultMessage:
        def __init__(self, structured_output: Any, result: str | None = None) -> None:
            self.structured_output = structured_output
            self.result = result

    async def query(prompt: str, options: Any):  # type: ignore[no-untyped-def]
        prompts.append(prompt)
        index = min(len(prompts) - 1, len(outputs) - 1)
        yield ResultMessage(outputs[index])

    module.ClaudeAgentOptions = ClaudeAgentOptions
    module.ResultMessage = ResultMessage
    module.query = query
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", module)


def test_diagnosis_decision_rejects_unauthorized_parameters() -> None:
    with pytest.raises(ValidationError):
        DiagnosisDecision.model_validate(_invalid_output())


def test_claude_agent_retries_after_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts: list[str] = []
    _install_fake_sdk(
        monkeypatch,
        outputs=[_invalid_output(), _valid_output()],
        prompts=prompts,
    )

    agent = ClaudeDiagnosisAgent(
        model="test-model",
        max_correction_attempts=2,
    )
    result = asyncio.run(
        agent.diagnose(
            _alert(),
            evidence={"health_check": False},
        )
    )

    assert result.recommended_action == "restart_service"
    assert result.action_parameters == {"service_name": "demo-api"}
    assert len(prompts) == 2
    assert "自动纠错任务" in prompts[1]
    assert "container_id" in prompts[1]


def test_claude_agent_stops_after_max_corrections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts: list[str] = []
    _install_fake_sdk(
        monkeypatch,
        outputs=[_invalid_output()],
        prompts=prompts,
    )

    agent = ClaudeDiagnosisAgent(
        model="test-model",
        max_correction_attempts=2,
    )

    with pytest.raises(ClaudeAgentUnavailableError, match="自动纠错 2 次"):
        asyncio.run(
            agent.diagnose(
                _alert(),
                evidence={"health_check": False},
            )
        )

    # 首次生成 + 2 次纠错
    assert len(prompts) == 3
