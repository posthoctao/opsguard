from app.core.enums import IncidentStatus


_ALLOWED_TRANSITIONS: dict[IncidentStatus, set[IncidentStatus]] = {
    IncidentStatus.OPEN: {
        IncidentStatus.COLLECTING_EVIDENCE,
        IncidentStatus.ESCALATED,
        IncidentStatus.FAILED,
    },
    IncidentStatus.COLLECTING_EVIDENCE: {
        IncidentStatus.DIAGNOSING,
        IncidentStatus.ESCALATED,
        IncidentStatus.FAILED,
    },
    IncidentStatus.DIAGNOSING: {
        IncidentStatus.PLANNING,
        IncidentStatus.ESCALATED,
        IncidentStatus.FAILED,
    },
    IncidentStatus.PLANNING: {
        IncidentStatus.WAITING_FOR_APPROVAL,
        IncidentStatus.REMEDIATING,
        IncidentStatus.ESCALATED,
        IncidentStatus.FAILED,
    },
    IncidentStatus.WAITING_FOR_APPROVAL: {
        IncidentStatus.REMEDIATING,
        IncidentStatus.ESCALATED,
        IncidentStatus.FAILED,
    },
    IncidentStatus.REMEDIATING: {
        IncidentStatus.VERIFYING,
        IncidentStatus.ESCALATED,
        IncidentStatus.FAILED,
    },
    IncidentStatus.VERIFYING: {
        IncidentStatus.RESOLVED,
        IncidentStatus.ESCALATED,
        IncidentStatus.FAILED,
    },
    IncidentStatus.RESOLVED: set(),
    IncidentStatus.ESCALATED: set(),
    IncidentStatus.FAILED: set(),
}


class InvalidTransitionError(ValueError):
    pass


def ensure_transition(current: IncidentStatus, target: IncidentStatus) -> None:
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise InvalidTransitionError(f"不允许的 Incident 状态转换：{current} -> {target}")
