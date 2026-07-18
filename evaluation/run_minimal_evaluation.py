from __future__ import annotations

import argparse
import csv
import json
import statistics
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx


SCENARIOS: dict[str, dict[str, Any]] = {
    "service_unavailable": {
        "alert_type": "ServiceUnavailable",
        "summary": "demo-api 健康检查失败",
        "expected_action": "restart_service",
        "approval_expected": False,
    },
    "deploy_regression": {
        "alert_type": "HighErrorRateAfterDeploy",
        "summary": "部署后 5xx 错误率上升",
        "expected_action": "rollback_deployment",
        "approval_expected": True,
    },
    "high_latency": {
        "alert_type": "HighLatency",
        "summary": "demo-api 延迟超过阈值",
        "expected_action": "restart_service",
        "approval_expected": False,
    },
}

INCIDENT_STOP_STATUSES = {
    "WAITING_FOR_APPROVAL",
    "RESOLVED",
    "ESCALATED",
    "FAILED",
}

REPAIR_STOP_STATUSES = {
    "PATCH_READY",
    "FAILED",
}


@dataclass
class IncidentEvaluationRow:
    run_type: str
    scenario: str
    run_number: int
    success: bool
    incident_id: str
    final_status: str
    diagnosis_present: bool
    diagnosis_confidence: float | None
    expected_action: str
    selected_action: str
    action_correct: bool
    approval_expected: bool
    approval_triggered: bool
    approval_flow_correct: bool
    verification_success: bool
    duration_seconds: float
    tool_duration_ms: int | None
    error: str


@dataclass
class RepairEvaluationRow:
    run_type: str
    scenario: str
    run_number: int
    success: bool
    incident_id: str
    repair_job_id: str
    final_status: str
    tests_passed: bool
    changed_files: str
    only_allowed_source_changed: bool
    duration_seconds: float
    error: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="运行故障诊断与受控修复项目的最小评测。"
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8001",
        help="宿主机访问后端的地址，默认 http://127.0.0.1:8001",
    )
    parser.add_argument(
        "--runs-per-scenario",
        type=int,
        default=3,
        help="每种运行时故障重复次数，默认 3。",
    )
    parser.add_argument(
        "--repair-runs",
        type=int,
        default=2,
        help="代码修复任务重复次数，默认 2；设为 0 可跳过。",
    )
    parser.add_argument(
        "--incident-timeout",
        type=float,
        default=120.0,
        help="单个 Incident 最长等待秒数。",
    )
    parser.add_argument(
        "--repair-timeout",
        type=float,
        default=300.0,
        help="单个代码修复任务最长等待秒数。",
    )
    parser.add_argument(
        "--output-dir",
        default="evaluation/results",
        help="评测结果目录。",
    )
    parser.add_argument(
        "--reviewer",
        default="Tao Huang",
        help="高风险回滚审批人。",
    )
    return parser.parse_args()


def request_json(
    client: httpx.Client,
    method: str,
    path: str,
    **kwargs: Any,
) -> dict[str, Any]:
    response = client.request(method, path, **kwargs)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        body = response.text[:2000]
        raise RuntimeError(
            f"{method} {path} 返回 HTTP {response.status_code}: {body}"
        ) from exc

    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"{method} {path} 返回的 JSON 不是对象。")
    return payload


def wait_for_status(
    client: httpx.Client,
    path: str,
    terminal_statuses: set[str],
    timeout_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_payload: dict[str, Any] | None = None

    while time.monotonic() < deadline:
        last_payload = request_json(client, "GET", path)
        status = str(last_payload.get("status", ""))
        if status in terminal_statuses:
            return last_payload
        time.sleep(0.5)

    raise TimeoutError(
        f"等待 {path} 进入 {sorted(terminal_statuses)} 超时；"
        f"最后结果：{last_payload}"
    )


def selected_action_from_incident(incident: dict[str, Any]) -> str:
    plan = incident.get("remediation_plan") or {}
    if isinstance(plan, dict) and plan.get("action_name"):
        return str(plan["action_name"])

    diagnosis = incident.get("diagnosis") or {}
    if isinstance(diagnosis, dict) and diagnosis.get("recommended_action"):
        return str(diagnosis["recommended_action"])

    return ""


def tool_duration_from_incident(incident: dict[str, Any]) -> int | None:
    executions = incident.get("tool_executions") or []
    if not isinstance(executions, list) or not executions:
        return None

    duration = executions[-1].get("duration_ms")
    return int(duration) if duration is not None else None


def run_incident_evaluation(
    client: httpx.Client,
    scenario_name: str,
    run_number: int,
    timeout_seconds: float,
    reviewer: str,
) -> tuple[IncidentEvaluationRow, str | None]:
    scenario = SCENARIOS[scenario_name]
    started = time.monotonic()
    incident_id = ""
    deploy_incident_for_repair: str | None = None

    try:
        request_json(client, "POST", "/api/v1/runtime/reset")
        request_json(
            client,
            "POST",
            "/api/v1/runtime/faults",
            json={"fault_type": scenario_name},
        )

        accepted = request_json(
            client,
            "POST",
            "/api/v1/alerts",
            json={
                "service_name": "demo-api",
                "alert_type": scenario["alert_type"],
                "severity": "critical",
                "summary": scenario["summary"],
                "labels": {
                    "environment": "最小评测",
                    "scenario": scenario_name,
                    "run_number": str(run_number),
                },
                "annotations": {
                    "evaluation": "minimal",
                },
            },
        )

        incident = accepted["incident"]
        incident_id = str(incident["id"])

        result = wait_for_status(
            client,
            f"/api/v1/incidents/{incident_id}",
            INCIDENT_STOP_STATUSES,
            timeout_seconds,
        )

        approval_triggered = result.get("status") == "WAITING_FOR_APPROVAL"

        if approval_triggered and scenario["approval_expected"]:
            request_json(
                client,
                "POST",
                f"/api/v1/incidents/{incident_id}/approve",
                json={
                    "approved_by": reviewer,
                    "note": "最小评测中批准预期的高风险回滚操作。",
                },
            )
            result = wait_for_status(
                client,
                f"/api/v1/incidents/{incident_id}",
                {"RESOLVED", "ESCALATED", "FAILED"},
                timeout_seconds,
            )

        selected_action = selected_action_from_incident(result)
        diagnosis = result.get("diagnosis") or {}
        verification = result.get("verification") or {}

        diagnosis_present = isinstance(diagnosis, dict) and bool(diagnosis)
        confidence_value = (
            diagnosis.get("confidence") if isinstance(diagnosis, dict) else None
        )
        confidence = (
            float(confidence_value) if confidence_value is not None else None
        )
        verification_success = bool(
            isinstance(verification, dict) and verification.get("success")
        )
        action_correct = selected_action == scenario["expected_action"]
        approval_flow_correct = (
            approval_triggered == scenario["approval_expected"]
        )
        final_status = str(result.get("status", ""))
        success = (
            final_status == "RESOLVED"
            and diagnosis_present
            and action_correct
            and approval_flow_correct
            and verification_success
        )

        if scenario_name == "deploy_regression" and final_status == "RESOLVED":
            deploy_incident_for_repair = incident_id

        return (
            IncidentEvaluationRow(
                run_type="incident",
                scenario=scenario_name,
                run_number=run_number,
                success=success,
                incident_id=incident_id,
                final_status=final_status,
                diagnosis_present=diagnosis_present,
                diagnosis_confidence=confidence,
                expected_action=str(scenario["expected_action"]),
                selected_action=selected_action,
                action_correct=action_correct,
                approval_expected=bool(scenario["approval_expected"]),
                approval_triggered=approval_triggered,
                approval_flow_correct=approval_flow_correct,
                verification_success=verification_success,
                duration_seconds=round(time.monotonic() - started, 3),
                tool_duration_ms=tool_duration_from_incident(result),
                error=str(result.get("error_message") or ""),
            ),
            deploy_incident_for_repair,
        )

    except Exception as exc:
        return (
            IncidentEvaluationRow(
                run_type="incident",
                scenario=scenario_name,
                run_number=run_number,
                success=False,
                incident_id=incident_id,
                final_status="ERROR",
                diagnosis_present=False,
                diagnosis_confidence=None,
                expected_action=str(scenario["expected_action"]),
                selected_action="",
                action_correct=False,
                approval_expected=bool(scenario["approval_expected"]),
                approval_triggered=False,
                approval_flow_correct=False,
                verification_success=False,
                duration_seconds=round(time.monotonic() - started, 3),
                tool_duration_ms=None,
                error=f"{type(exc).__name__}: {exc}",
            ),
            None,
        )


def run_repair_evaluation(
    client: httpx.Client,
    incident_id: str,
    run_number: int,
    timeout_seconds: float,
) -> RepairEvaluationRow:
    started = time.monotonic()
    repair_job_id = ""

    try:
        created = request_json(
            client,
            "POST",
            f"/api/v1/incidents/{incident_id}/repairs",
            json={
                "requested_by": "Tao Huang",
                "source_profile": "demo-buffer-bug",
                "instructions": (
                    "实施最小且安全的修复；只允许修改白名单源码，"
                    "不得修改测试文件或依赖配置。"
                    "读取相关代码和测试后直接实施最小修改，"
                    "运行指定测试，测试通过后立即结束任务，"
                    "不要重复读取相同文件或重复运行已经通过的测试。"
                ),
            },
        )
        repair_job_id = str(created["id"])

        result = wait_for_status(
            client,
            f"/api/v1/repairs/{repair_job_id}",
            REPAIR_STOP_STATUSES,
            timeout_seconds,
        )

        changed_files_raw = result.get("changed_files") or []
        changed_files = [
            str(item) for item in changed_files_raw
        ] if isinstance(changed_files_raw, list) else []

        only_allowed_source_changed = (
            changed_files == ["sample_service/cache.py"]
        )
        tests_passed = bool(result.get("tests_passed"))
        final_status = str(result.get("status", ""))
        success = (
            final_status == "PATCH_READY"
            and tests_passed
            and only_allowed_source_changed
        )

        return RepairEvaluationRow(
            run_type="code_repair",
            scenario="demo_buffer_bug",
            run_number=run_number,
            success=success,
            incident_id=incident_id,
            repair_job_id=repair_job_id,
            final_status=final_status,
            tests_passed=tests_passed,
            changed_files=";".join(changed_files),
            only_allowed_source_changed=only_allowed_source_changed,
            duration_seconds=round(time.monotonic() - started, 3),
            error=str(result.get("error_message") or ""),
        )

    except Exception as exc:
        return RepairEvaluationRow(
            run_type="code_repair",
            scenario="demo_buffer_bug",
            run_number=run_number,
            success=False,
            incident_id=incident_id,
            repair_job_id=repair_job_id,
            final_status="ERROR",
            tests_passed=False,
            changed_files="",
            only_allowed_source_changed=False,
            duration_seconds=round(time.monotonic() - started, 3),
            error=f"{type(exc).__name__}: {exc}",
        )


def percentage(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator * 100, 1)


def average(values: list[float]) -> float:
    return round(statistics.mean(values), 2) if values else 0.0


def write_csv(
    path: Path,
    incident_rows: list[IncidentEvaluationRow],
    repair_rows: list[RepairEvaluationRow],
) -> None:
    fieldnames = [
        "run_type",
        "scenario",
        "run_number",
        "success",
        "incident_id",
        "repair_job_id",
        "final_status",
        "diagnosis_present",
        "diagnosis_confidence",
        "expected_action",
        "selected_action",
        "action_correct",
        "approval_expected",
        "approval_triggered",
        "approval_flow_correct",
        "verification_success",
        "tests_passed",
        "changed_files",
        "only_allowed_source_changed",
        "duration_seconds",
        "tool_duration_ms",
        "error",
    ]

    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()

        for row in incident_rows:
            raw = asdict(row)
            raw["repair_job_id"] = ""
            raw["tests_passed"] = ""
            raw["changed_files"] = ""
            raw["only_allowed_source_changed"] = ""
            writer.writerow(raw)

        for row in repair_rows:
            raw = asdict(row)
            raw["diagnosis_present"] = ""
            raw["diagnosis_confidence"] = ""
            raw["expected_action"] = ""
            raw["selected_action"] = ""
            raw["action_correct"] = ""
            raw["approval_expected"] = ""
            raw["approval_triggered"] = ""
            raw["approval_flow_correct"] = ""
            raw["verification_success"] = ""
            raw["tool_duration_ms"] = ""
            writer.writerow(raw)


def write_summary(
    path: Path,
    base_url: str,
    incident_rows: list[IncidentEvaluationRow],
    repair_rows: list[RepairEvaluationRow],
) -> None:
    incident_total = len(incident_rows)
    incident_successes = sum(row.success for row in incident_rows)
    diagnosis_completed = sum(row.diagnosis_present for row in incident_rows)
    action_correct = sum(row.action_correct for row in incident_rows)
    approval_correct = sum(row.approval_flow_correct for row in incident_rows)
    verification_successes = sum(
        row.verification_success for row in incident_rows
    )

    repair_total = len(repair_rows)
    repair_successes = sum(row.success for row in repair_rows)
    repair_tests_passed = sum(row.tests_passed for row in repair_rows)
    repair_scope_safe = sum(
        row.only_allowed_source_changed for row in repair_rows
    )

    lines = [
        "# 最小评测结果",
        "",
        f"- 评测时间：{datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"- 后端地址：`{base_url}`",
        f"- 运行时故障样本数：{incident_total}",
        f"- 代码修复样本数：{repair_total}",
        "",
        "## 总体指标",
        "",
        "| 指标 | 结果 |",
        "|---|---:|",
        (
            f"| 运行时完整成功率 | "
            f"{incident_successes}/{incident_total} "
            f"({percentage(incident_successes, incident_total)}%) |"
        ),
        (
            f"| 诊断完成率 | "
            f"{diagnosis_completed}/{incident_total} "
            f"({percentage(diagnosis_completed, incident_total)}%) |"
        ),
        (
            f"| 修复动作选择准确率 | "
            f"{action_correct}/{incident_total} "
            f"({percentage(action_correct, incident_total)}%) |"
        ),
        (
            f"| 审批流程正确率 | "
            f"{approval_correct}/{incident_total} "
            f"({percentage(approval_correct, incident_total)}%) |"
        ),
        (
            f"| 修复后验证通过率 | "
            f"{verification_successes}/{incident_total} "
            f"({percentage(verification_successes, incident_total)}%) |"
        ),
        (
            f"| 平均 Incident 处理时间 | "
            f"{average([row.duration_seconds for row in incident_rows])} 秒 |"
        ),
    ]

    if repair_total:
        lines.extend(
            [
                (
                    f"| 代码修复完整成功率 | "
                    f"{repair_successes}/{repair_total} "
                    f"({percentage(repair_successes, repair_total)}%) |"
                ),
                (
                    f"| 代码修复测试通过率 | "
                    f"{repair_tests_passed}/{repair_total} "
                    f"({percentage(repair_tests_passed, repair_total)}%) |"
                ),
                (
                    f"| 修改范围合规率 | "
                    f"{repair_scope_safe}/{repair_total} "
                    f"({percentage(repair_scope_safe, repair_total)}%) |"
                ),
                (
                    f"| 平均代码修复时间 | "
                    f"{average([row.duration_seconds for row in repair_rows])} 秒 |"
                ),
            ]
        )

    lines.extend(
        [
            "",
            "## 分场景结果",
            "",
            "| 场景 | 次数 | 完整成功率 | 动作准确率 | 平均处理时间 |",
            "|---|---:|---:|---:|---:|",
        ]
    )

    for scenario_name in SCENARIOS:
        rows = [
            row for row in incident_rows if row.scenario == scenario_name
        ]
        successes = sum(row.success for row in rows)
        correct_actions = sum(row.action_correct for row in rows)
        lines.append(
            f"| `{scenario_name}` | {len(rows)} | "
            f"{percentage(successes, len(rows))}% | "
            f"{percentage(correct_actions, len(rows))}% | "
            f"{average([row.duration_seconds for row in rows])} 秒 |"
        )

    lines.extend(
        [
            "",
            "## 运行明细",
            "",
            "| 类型 | 场景 | 序号 | 成功 | 最终状态 | 动作/测试 | 耗时 |",
            "|---|---|---:|---|---|---|---:|",
        ]
    )

    for row in incident_rows:
        lines.append(
            f"| Incident | `{row.scenario}` | {row.run_number} | "
            f"{'是' if row.success else '否'} | `{row.final_status}` | "
            f"`{row.selected_action or '-'}` | {row.duration_seconds} 秒 |"
        )

    for row in repair_rows:
        lines.append(
            f"| Code Repair | `{row.scenario}` | {row.run_number} | "
            f"{'是' if row.success else '否'} | `{row.final_status}` | "
            f"{'测试通过' if row.tests_passed else '测试未通过'} | "
            f"{row.duration_seconds} 秒 |"
        )

    failed_errors = [
        row.error for row in [*incident_rows, *repair_rows] if row.error
    ]
    if failed_errors:
        lines.extend(["", "## 失败信息", ""])
        for error in failed_errors:
            lines.append(f"- {error}")

    lines.extend(
        [
            "",
            "## 说明",
            "",
            "- 完整成功要求：诊断结果存在、动作选择正确、审批路径正确、最终状态为 `RESOLVED`，且确定性验证通过。",
            "- 代码修复成功要求：任务进入 `PATCH_READY`、独立测试通过，且只修改 `sample_service/cache.py`。",
            "- 本评测规模较小，只用于求职项目的可复现性验证，不代表生产环境基准测试。",
            "",
        ]
    )

    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    if args.runs_per_scenario < 1:
        raise SystemExit("--runs-per-scenario 必须至少为 1。")
    if args.repair_runs < 0:
        raise SystemExit("--repair-runs 不能小于 0。")

    base_url = args.base_url.rstrip("/")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = output_dir / f"minimal_evaluation_{timestamp}.csv"
    summary_path = output_dir / f"minimal_evaluation_summary_{timestamp}.md"

    incident_rows: list[IncidentEvaluationRow] = []
    repair_rows: list[RepairEvaluationRow] = []
    resolved_deploy_incidents: list[str] = []

    with httpx.Client(base_url=base_url, timeout=120.0) as client:
        print(f"检查后端：{base_url}")
        state = request_json(client, "GET", "/api/v1/runtime/state")
        print(
            "后端与演示服务可用："
            f"running={state.get('running')}, "
            f"version={state.get('version')}"
        )

        for scenario_name in SCENARIOS:
            for run_number in range(1, args.runs_per_scenario + 1):
                print(
                    f"\n[Incident] {scenario_name} "
                    f"{run_number}/{args.runs_per_scenario}"
                )
                row, deploy_incident = run_incident_evaluation(
                    client=client,
                    scenario_name=scenario_name,
                    run_number=run_number,
                    timeout_seconds=args.incident_timeout,
                    reviewer=args.reviewer,
                )
                incident_rows.append(row)
                if deploy_incident:
                    resolved_deploy_incidents.append(deploy_incident)

                print(
                    f"结果：success={row.success}, "
                    f"status={row.final_status}, "
                    f"action={row.selected_action or '-'}, "
                    f"duration={row.duration_seconds}s"
                )
                if row.error:
                    print(f"错误：{row.error}")

        if args.repair_runs:
            if not resolved_deploy_incidents:
                print(
                    "\n没有成功完成的 deploy_regression Incident，"
                    "跳过代码修复评测。"
                )
            else:
                source_incident_id = resolved_deploy_incidents[-1]
                for run_number in range(1, args.repair_runs + 1):
                    print(
                        f"\n[Code Repair] "
                        f"{run_number}/{args.repair_runs}"
                    )
                    row = run_repair_evaluation(
                        client=client,
                        incident_id=source_incident_id,
                        run_number=run_number,
                        timeout_seconds=args.repair_timeout,
                    )
                    repair_rows.append(row)
                    print(
                        f"结果：success={row.success}, "
                        f"status={row.final_status}, "
                        f"tests_passed={row.tests_passed}, "
                        f"duration={row.duration_seconds}s"
                    )
                    if row.error:
                        print(f"错误：{row.error}")

    write_csv(csv_path, incident_rows, repair_rows)
    write_summary(
        summary_path,
        base_url,
        incident_rows,
        repair_rows,
    )

    total = len(incident_rows) + len(repair_rows)
    passed = sum(row.success for row in incident_rows) + sum(
        row.success for row in repair_rows
    )

    print("\n==============================")
    print(f"最小评测完成：{passed}/{total} 条完整成功")
    print(f"CSV：{csv_path}")
    print(f"摘要：{summary_path}")
    print("==============================")


if __name__ == "__main__":
    main()