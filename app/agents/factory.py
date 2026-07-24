from app.agents.base import DiagnosisAgent
from app.agents.claude import ClaudeDiagnosisAgent
from app.agents.rules import RuleBasedDiagnosisAgent
from app.core.config import Settings


def build_diagnosis_agent(settings: Settings) -> DiagnosisAgent:
    if settings.ai_provider == "claude":
        return ClaudeDiagnosisAgent(
            model=settings.claude_model,
            max_turns=settings.claude_max_turns,
            timeout_seconds=settings.claude_timeout_seconds,
        )
    return RuleBasedDiagnosisAgent()
