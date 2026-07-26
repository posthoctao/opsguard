from __future__ import annotations

import argparse
import json
import mimetypes
import time
from pathlib import Path

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


def wait_for_incident(
    client: httpx.Client,
    incident_id: str,
    timeout_seconds: float = 90.0,
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
        f"Incident {incident_id} 未完成，最后状态为 {last}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="运行多模态故障诊断演示。")
    parser.add_argument("scenario", choices=SCENARIOS)
    parser.add_argument("image", type=Path, help="监控或报错截图路径")
    parser.add_argument("--base-url", default="http://localhost:8001")
    parser.add_argument("--approve", action="store_true")
    args = parser.parse_args()

    if not args.image.is_file():
        raise FileNotFoundError(args.image)

    mime_type = mimetypes.guess_type(args.image.name)[0]
    if mime_type not in {"image/png", "image/jpeg", "image/webp"}:
        raise ValueError("图片必须是 PNG、JPEG 或 WEBP。")

    scenario = SCENARIOS[args.scenario]
    with httpx.Client(base_url=args.base_url, timeout=120) as client:
        client.post("/api/v1/runtime/reset").raise_for_status()
        client.post(
            "/api/v1/runtime/faults",
            json={"fault_type": args.scenario},
        ).raise_for_status()

        accepted = client.post(
            "/api/v1/alerts",
            json={
                "service_name": "demo-api",
                "alert_type": scenario["alert_type"],
                "severity": "critical",
                "summary": scenario["summary"],
                "labels": {"environment": "多模态演示"},
            },
        )
        accepted.raise_for_status()
        incident_id = accepted.json()["incident"]["id"]

        with args.image.open("rb") as image_file:
            analyzed = client.post(
                f"/api/v1/incidents/{incident_id}/visual-evidence",
                files={
                    "file": (
                        args.image.name,
                        image_file,
                        mime_type,
                    )
                },
            )
        analyzed.raise_for_status()
        print("视觉证据：")
        print(json.dumps(analyzed.json(), ensure_ascii=False, indent=2))

        process = client.post(f"/api/v1/incidents/{incident_id}/process")
        process.raise_for_status()
        result = wait_for_incident(client, incident_id)

        if result["status"] == "WAITING_FOR_APPROVAL" and args.approve:
            client.post(
                f"/api/v1/incidents/{incident_id}/approve",
                json={
                    "approved_by": "多模态演示审核人",
                    "note": "演示中批准回滚操作。",
                },
            ).raise_for_status()
            result = wait_for_incident(client, incident_id)

        print("\nIncident 最终结果：")
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
