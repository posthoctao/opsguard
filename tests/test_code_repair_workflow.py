from app.dependencies import set_repair_client_override
from app.schemas import (
    CodeRepairAgentReport,
    CodeRepairFileChange,
    CodeRepairWorkerResult,
)
from app.services.repair_client import RepairWorkerClient


class FakeRepairWorkerClient(RepairWorkerClient):
    async def run_repair(self, request):
        assert request.source_profile == "demo-buffer-bug"
        return CodeRepairWorkerResult(
            provider="rules",
            summary="已限制请求缓冲区容量。",
            root_cause="无界列表保留了所有请求标识。",
            changed_files=["sample_service/cache.py"],
            file_changes=[
                CodeRepairFileChange(
                    path="sample_service/cache.py",
                    content="from collections import deque\n",
                )
            ],
            diff_text="--- a/sample_service/cache.py\n+++ b/sample_service/cache.py\n",
            tests_passed=True,
            test_command=["python", "-m", "pytest", "-q"],
            test_output="2 passed",
            agent_report=CodeRepairAgentReport(
                summary="已限制请求缓冲区容量。",
                root_cause="无界列表保留了所有请求标识。",
                files_changed=["sample_service/cache.py"],
            ),
        )


def _alert() -> dict:
    return {
        "service_name": "demo-api",
        "alert_type": "HighErrorRateAfterDeploy",
        "severity": "critical",
        "summary": "部署后 5xx 错误率上升",
        "labels": {"environment": "demo"},
    }


def test_tested_patch_requires_separate_human_approval(client):
    set_repair_client_override(FakeRepairWorkerClient())

    client.post("/api/v1/runtime/faults", json={"fault_type": "deploy_regression"})
    incident_id = client.post("/api/v1/alerts", json=_alert()).json()["incident"]["id"]
    client.post(
        f"/api/v1/incidents/{incident_id}/approve",
        json={"approved_by": "ops@example.com", "note": "已批准回滚。"},
    )

    created = client.post(
        f"/api/v1/incidents/{incident_id}/repairs",
        json={
            "requested_by": "developer@example.com",
            "source_profile": "demo-buffer-bug",
        },
    )
    assert created.status_code == 202
    repair_id = created.json()["id"]

    detail = client.get(f"/api/v1/repairs/{repair_id}").json()
    assert detail["status"] == "PATCH_READY"
    assert detail["tests_passed"] is True
    assert detail["changed_files"] == ["sample_service/cache.py"]
    assert detail["pull_request_url"] is None

    approved = client.post(
        f"/api/v1/repairs/{repair_id}/approve",
        json={"approved_by": "reviewer@example.com", "note": "补丁已完成审核。"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "APPROVED"

    incident = client.get(f"/api/v1/incidents/{incident_id}").json()
    assert incident["repair_jobs"][0]["status"] == "APPROVED"


def test_unapproved_patch_cannot_be_published(client):
    set_repair_client_override(FakeRepairWorkerClient())

    client.post("/api/v1/runtime/faults", json={"fault_type": "deploy_regression"})
    incident_id = client.post("/api/v1/alerts", json=_alert()).json()["incident"]["id"]
    client.post(
        f"/api/v1/incidents/{incident_id}/approve",
        json={"approved_by": "ops@example.com"},
    )
    repair_id = client.post(
        f"/api/v1/incidents/{incident_id}/repairs",
        json={"requested_by": "developer@example.com"},
    ).json()["id"]

    response = client.post(
        f"/api/v1/repairs/{repair_id}/publish-pr",
        json={"published_by": "developer@example.com"},
    )
    assert response.status_code == 409
