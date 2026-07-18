def _alert(alert_type: str, summary: str) -> dict:
    return {
        "service_name": "demo-api",
        "alert_type": alert_type,
        "severity": "critical",
        "summary": summary,
        "labels": {"environment": "demo"},
    }


def test_low_risk_incident_is_remediated_and_verified(client):
    fault = client.post("/api/v1/runtime/faults", json={"fault_type": "service_unavailable"})
    assert fault.status_code == 200
    assert fault.json()["running"] is False

    response = client.post(
        "/api/v1/alerts",
        json=_alert("ServiceUnavailable", "demo-api 健康检查失败"),
    )
    assert response.status_code == 202
    incident = response.json()["incident"]

    detail = client.get(f"/api/v1/incidents/{incident['id']}").json()
    assert detail["status"] == "RESOLVED"
    assert detail["verification"]["success"] is True
    assert detail["tool_executions"][0]["status"] == "SUCCEEDED"


def test_high_risk_rollback_waits_for_human_approval(client):
    client.post("/api/v1/runtime/faults", json={"fault_type": "deploy_regression"})
    response = client.post(
        "/api/v1/alerts",
        json=_alert("HighErrorRateAfterDeploy", "部署后 5xx 错误率上升"),
    )
    incident_id = response.json()["incident"]["id"]

    detail = client.get(f"/api/v1/incidents/{incident_id}").json()
    assert detail["status"] == "WAITING_FOR_APPROVAL"
    assert detail["tool_executions"] == []

    approved = client.post(
        f"/api/v1/incidents/{incident_id}/approve",
        json={"approved_by": "reviewer@example.com", "note": "已批准回滚。"},
    )
    assert approved.status_code == 200
    result = approved.json()
    assert result["status"] == "RESOLVED"
    assert result["tool_executions"][0]["action_name"] == "rollback_deployment"


def test_duplicate_active_alert_is_suppressed(client):
    client.post("/api/v1/runtime/faults", json={"fault_type": "deploy_regression"})
    payload = _alert("HighErrorRateAfterDeploy", "部署后 5xx 错误率上升")

    first = client.post("/api/v1/alerts", json=payload).json()
    second = client.post("/api/v1/alerts", json=payload).json()

    assert first["deduplicated"] is False
    assert second["deduplicated"] is True
    assert first["incident"]["id"] == second["incident"]["id"]
