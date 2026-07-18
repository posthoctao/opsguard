from __future__ import annotations

import argparse
import time

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(
        description="运行部署回滚与隔离式代码修复完整流程。"
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="后端 API 地址")
    parser.add_argument("--publish-pr", action="store_true", help="审批补丁后继续发布 GitHub PR")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    with httpx.Client(timeout=240.0) as client:
        client.post(
            f"{base_url}/api/v1/runtime/faults",
            json={"fault_type": "deploy_regression"},
        ).raise_for_status()
        alert = client.post(
            f"{base_url}/api/v1/alerts",
            json={
                "service_name": "demo-api",
                "alert_type": "HighErrorRateAfterDeploy",
                "severity": "critical",
                "summary": "部署后 5xx 错误率上升",
                "labels": {"environment": "演示环境"},
            },
        )
        alert.raise_for_status()
        incident_id = alert.json()["incident"]["id"]

        detail = _wait_for_status(
            client,
            f"{base_url}/api/v1/incidents/{incident_id}",
            {"WAITING_FOR_APPROVAL", "FAILED", "ESCALATED"},
        )
        print(f"Incident {incident_id} 当前状态：{detail['status']}")
        if detail["status"] != "WAITING_FOR_APPROVAL":
            raise SystemExit("Incident 未进入等待回滚审批状态。")

        approved = client.post(
            f"{base_url}/api/v1/incidents/{incident_id}/approve",
            json={"approved_by": "演示运维审核人", "note": "已批准回滚。"},
        )
        approved.raise_for_status()
        print(f"运行时修复结果：{approved.json()['status']}")

        repair = client.post(
            f"{base_url}/api/v1/incidents/{incident_id}/repairs",
            json={
                "requested_by": "演示开发人员",
                "source_profile": "demo-buffer-bug",
                "instructions": "实施最小且安全的修复，不得修改测试文件。",
            },
        )
        repair.raise_for_status()
        repair_id = repair.json()["id"]
        patch = _wait_for_status(
            client,
            f"{base_url}/api/v1/repairs/{repair_id}",
            {"PATCH_READY", "FAILED"},
            timeout_seconds=240,
        )
        print(f"代码修复任务 {repair_id} 当前状态：{patch['status']}")
        print(f"修改文件：{patch['changed_files']}")
        print(f"测试是否通过：{patch['tests_passed']}")
        if patch["status"] != "PATCH_READY":
            raise SystemExit(patch.get("error_message") or "代码修复失败。")

        approval = client.post(
            f"{base_url}/api/v1/repairs/{repair_id}/approve",
            json={"approved_by": "演示代码审核人", "note": "补丁已完成审核。"},
        )
        approval.raise_for_status()
        print(f"补丁审批结果：{approval.json()['status']}")

        if args.publish_pr:
            published = client.post(
                f"{base_url}/api/v1/repairs/{repair_id}/publish-pr",
                json={"published_by": "演示代码审核人"},
            )
            published.raise_for_status()
            print(f"Pull Request 地址：{published.json()['pull_request_url']}")


def _wait_for_status(
    client: httpx.Client,
    url: str,
    terminal: set[str],
    timeout_seconds: int = 60,
) -> dict:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        response = client.get(url)
        response.raise_for_status()
        payload = response.json()
        if payload["status"] in terminal:
            return payload
        time.sleep(0.5)
    raise TimeoutError(f"等待目标状态 {sorted(terminal)} 超时")


if __name__ == "__main__":
    main()
