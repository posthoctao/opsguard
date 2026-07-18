from __future__ import annotations

import argparse
import json
import time

import httpx


SCENARIOS = {
    "service_unavailable": {
        "alert_type": "ServiceUnavailable",
        "summary": "demo-api 健康检查失败",
    },
    "deploy_regression": {
        "alert_type": "HighErrorRateAfterDeploy",
        "summary": "部署后 5xx 错误率上升",
    },
    "high_latency": {
        "alert_type": "HighLatency",
        "summary": "demo-api 延迟超过阈值",
    },
}

STOP_STATUSES = {"WAITING_FOR_APPROVAL", "RESOLVED", "ESCALATED", "FAILED"}


def _wait_for_incident(
    client: httpx.Client,
    incident_id: str,
    timeout_seconds: float = 60.0,
) -> dict:
    deadline = time.monotonic() + timeout_seconds
    last: dict | None = None
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/incidents/{incident_id}")
        response.raise_for_status()
        last = response.json()
        if last["status"] in STOP_STATUSES:
            return last
        time.sleep(0.5)
    raise TimeoutError(
        f"Incident {incident_id} 未在 {timeout_seconds} 秒内完成，最后状态为 {last}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="运行一个端到端故障处理场景。")
    parser.add_argument("scenario", choices=SCENARIOS)
    parser.add_argument("--base-url", default="http://localhost:8000", help="后端 API 地址")
    parser.add_argument(
        "--approve",
        action="store_true",
        help="在演示中自动批准高风险修复计划。",
    )
    args = parser.parse_args()

    scenario = SCENARIOS[args.scenario]
    with httpx.Client(base_url=args.base_url, timeout=65) as client:
        client.post("/api/v1/runtime/reset").raise_for_status()
        fault = client.post("/api/v1/runtime/faults", json={"fault_type": args.scenario})
        fault.raise_for_status()
        print("已注入故障：")
        print(json.dumps(fault.json(), indent=2))

        accepted = client.post(
            "/api/v1/alerts",
            json={
                "service_name": "demo-api",
                "alert_type": scenario["alert_type"],
                "severity": "critical",
                "summary": scenario["summary"],
                "labels": {"environment": "演示环境"},
            },
        )
        accepted.raise_for_status()
        incident_id = accepted.json()["incident"]["id"]
        result = _wait_for_incident(client, incident_id)

        if result["status"] == "WAITING_FOR_APPROVAL" and args.approve:
            approved = client.post(
                f"/api/v1/incidents/{incident_id}/approve",
                json={"approved_by": "演示审核人", "note": "由演示脚本自动批准。"},
            )
            approved.raise_for_status()
            result = _wait_for_incident(client, incident_id)

        print("\nIncident 最终结果：")
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
