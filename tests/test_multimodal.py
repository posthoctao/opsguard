from __future__ import annotations

import asyncio
import sys
import types
from typing import Any

import pytest
from pydantic import ValidationError

from app.agents.vision import ClaudeVisionEvidenceAgent
from app.schemas import VisualEvidence
from app.services.orchestrator import IncidentOrchestrator


def valid_visual_evidence() -> VisualEvidence:
    return VisualEvidence(
        evidence_type="monitoring_chart",
        summary="部署后错误率明显升高。",
        detected_text=["HTTP 5xx Rate", "demo-api"],
        detected_metrics={"error_rate": "31%"},
        anomalies=["错误率在部署后快速上升"],
        related_services=["demo-api"],
        limitations=[],
        confidence=0.92,
    )


def test_visual_evidence_rejects_extra_fields() -> None:
    payload = valid_visual_evidence().model_dump()
    payload["command"] = "docker restart demo-api"
    with pytest.raises(ValidationError):
        VisualEvidence.model_validate(payload)


def test_merge_evidence_preserves_only_visual_evidence() -> None:
    merged = IncidentOrchestrator._merge_evidence(
        runtime_evidence={
            "health_check": False,
            "current_version": "v2-buggy",
        },
        existing_evidence={
            "health_check": True,
            "stale_value": "不要保留",
            "visual_evidence": [{"id": "visual-1"}],
        },
    )
    assert merged["health_check"] is False
    assert merged["current_version"] == "v2-buggy"
    assert merged["visual_evidence"] == [{"id": "visual-1"}]
    assert "stale_value" not in merged


def test_vision_agent_sends_image_and_returns_structured_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    expected = valid_visual_evidence()

    class FakeMessages:
        async def parse(self, **kwargs: Any) -> Any:
            captured.update(kwargs)
            return types.SimpleNamespace(parsed_output=expected)

    class FakeAsyncAnthropic:
        def __init__(self) -> None:
            self.messages = FakeMessages()

    fake_module = types.ModuleType("anthropic")
    fake_module.AsyncAnthropic = FakeAsyncAnthropic
    monkeypatch.setitem(sys.modules, "anthropic", fake_module)

    agent = ClaudeVisionEvidenceAgent(
        model="test-vision-model",
        timeout_seconds=5,
    )
    result = asyncio.run(
        agent.analyze(
            image_bytes=b"\x89PNG\r\n\x1a\nfake",
            media_type="image/png",
            incident_context={"service_name": "demo-api"},
        )
    )

    assert result == expected
    assert captured["model"] == "test-vision-model"
    content = captured["messages"][0]["content"]
    assert content[0]["type"] == "image"
    assert content[0]["source"]["media_type"] == "image/png"
    assert content[1]["type"] == "text"
    assert captured["output_format"] is VisualEvidence
