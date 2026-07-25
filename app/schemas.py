from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.enums import (
    CodeRepairStatus,
    IncidentStatus,
    RiskLevel,
    Severity,
    ToolExecutionStatus,
)


class AlertCreate(BaseModel):
    """创建故障告警时使用的请求模型。"""

    service_name: str = Field(min_length=1, max_length=120, description="发生故障的服务名称")
    alert_type: str = Field(min_length=1, max_length=120, description="告警类型，例如 ServiceUnavailable")
    severity: Severity = Field(default=Severity.WARNING, description="告警严重程度")
    summary: str = Field(min_length=1, description="告警摘要")
    labels: dict[str, str] = Field(default_factory=dict, description="告警标签")
    metrics: dict[str, float | int | str] = Field(default_factory=dict, description="告警携带的指标数据")
    annotations: dict[str, str] = Field(default_factory=dict, description="告警补充说明")
    fingerprint: str | None = Field(default=None, description="可选告警指纹；未提供时由后端自动生成")


class DiagnosisDecision(BaseModel):
    """AI 或规则诊断组件返回的结构化诊断结果。"""

    # 禁止模型在顶层编造 Schema 之外的字段。
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(description="诊断摘要")
    root_cause: str = Field(description="推断的根因")
    confidence: float = Field(ge=0.0, le=1.0, description="诊断置信度，范围为 0 到 1")
    evidence: list[str] = Field(min_length=1, description="支持诊断结论的证据")
    recommended_action: Literal[
        "restart_service",
        "rollback_deployment",
        "no_safe_action",
    ] = Field(description="建议动作；最终是否执行仍由后端策略引擎决定")
    action_parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="建议动作参数",
    )

    @model_validator(mode="after")
    def validate_action_parameters(self) -> "DiagnosisDecision":
        """按动作校验参数白名单，让非法参数进入自动纠错流程。"""

        parameter_rules: dict[str, tuple[set[str], set[str]]] = {
            "restart_service": (
                {"service_name"},
                {"service_name"},
            ),
            "rollback_deployment": (
                {"service_name", "target_version"},
                {"service_name", "target_version"},
            ),
            "no_safe_action": (
                set(),
                set(),
            ),
        }
        allowed, required = parameter_rules[self.recommended_action]
        provided = set(self.action_parameters)

        unexpected = sorted(provided - allowed)
        missing = sorted(required - provided)

        errors: list[str] = []
        if unexpected:
            errors.append(f"包含未授权参数：{', '.join(unexpected)}")
        if missing:
            errors.append(f"缺少必填参数：{', '.join(missing)}")

        service_name = self.action_parameters.get("service_name")
        if "service_name" in allowed and (
            not isinstance(service_name, str) or not service_name.strip()
        ):
            errors.append("service_name 必须是非空字符串")

        target_version = self.action_parameters.get("target_version")
        if "target_version" in allowed and (
            not isinstance(target_version, str) or not target_version.strip()
        ):
            errors.append("target_version 必须是非空字符串")

        if errors:
            raise ValueError("；".join(errors))

        return self


class RemediationPlan(BaseModel):
    """后端根据诊断结果生成的修复计划。"""

    action_name: str = Field(description="修复动作名称")
    parameters: dict[str, Any] = Field(default_factory=dict, description="修复动作参数")
    expected_outcome: str = Field(description="预期修复结果")
    verification_checks: list[str] = Field(default_factory=list, description="修复后需要执行的验证项")


class PolicyDecision(BaseModel):
    """服务端策略引擎对修复计划的判定结果。"""

    action_name: str = Field(description="待评估动作名称")
    risk_level: RiskLevel = Field(description="动作风险等级")
    approval_required: bool = Field(description="是否需要人工审批")
    allowed: bool = Field(description="是否允许执行")
    reason: str = Field(description="策略判定原因")


class VerificationResult(BaseModel):
    """运行时修复后的确定性验证结果。"""

    success: bool = Field(description="恢复验证是否通过")
    checks: dict[str, Any] = Field(default_factory=dict, description="各项验证检查结果")
    message: str = Field(description="验证结果说明")


class IncidentEventRead(BaseModel):
    """Incident 时间线事件。"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="事件记录 ID")
    event_type: str = Field(description="机器可读的事件类型")
    message: str = Field(description="中文事件说明")
    data: dict[str, Any] = Field(description="事件附加数据")
    created_at: datetime = Field(description="事件创建时间")


class ToolExecutionRead(BaseModel):
    """受控工具执行审计记录。"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="工具执行记录 ID")
    action_name: str = Field(description="执行的动作名称")
    risk_level: RiskLevel = Field(description="动作风险等级")
    status: ToolExecutionStatus = Field(description="工具执行状态")
    request_payload: dict[str, Any] = Field(description="执行请求参数")
    result_payload: dict[str, Any] | None = Field(description="执行结果")
    error_message: str | None = Field(description="执行失败时的错误信息")
    started_at: datetime | None = Field(description="开始执行时间")
    finished_at: datetime | None = Field(description="结束执行时间")
    duration_ms: int | None = Field(description="执行耗时，单位毫秒")


class RepairEventRead(BaseModel):
    """代码修复任务时间线事件。"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="事件记录 ID")
    event_type: str = Field(description="机器可读的事件类型")
    message: str = Field(description="中文事件说明")
    data: dict[str, Any] = Field(description="事件附加数据")
    created_at: datetime = Field(description="事件创建时间")


class CodeRepairFileChange(BaseModel):
    """代码修复产生的单个文件变更。"""

    path: str = Field(min_length=1, max_length=500, description="相对文件路径")
    content: str = Field(description="修改后的完整文件内容")


class CodeRepairWorkerRequest(BaseModel):
    """后端发送给隔离式 Repair Worker 的任务请求。"""

    job_id: str = Field(description="代码修复任务 ID")
    incident_id: str = Field(description="关联的 Incident ID")
    source_profile: str = Field(description="后端白名单中的源码模板")
    issue_summary: str = Field(description="问题摘要")
    root_cause: str = Field(description="已知或推断的根因")
    evidence: dict[str, Any] = Field(default_factory=dict, description="故障相关证据")
    instructions: str | None = Field(default=None, description="人工补充的修复要求")


class CodeRepairAgentReport(BaseModel):
    """代码修复 Agent 返回的结构化报告。"""

    summary: str = Field(description="修复摘要")
    root_cause: str = Field(description="代码层根因")
    files_changed: list[str] = Field(default_factory=list, description="Agent 声明修改的文件")
    tests_attempted: list[str] = Field(default_factory=list, description="Agent 尝试执行的测试或检查")
    notes: list[str] = Field(default_factory=list, description="补充说明")


class RepairVerificationRequest(BaseModel):
    """请求独立验证服务执行固定测试。"""

    job_id: str = Field(description="代码修复任务 ID")


class RepairVerificationResult(BaseModel):
    """独立验证服务返回的测试结果。"""

    tests_passed: bool = Field(description="测试是否通过")
    return_code: int = Field(description="测试进程退出码")
    test_command: list[str] = Field(description="实际执行的固定测试命令")
    test_output: str = Field(description="测试标准输出与错误输出")


class CodeRepairWorkerResult(BaseModel):
    """隔离式 Repair Worker 返回给后端的完整结果。"""

    provider: str = Field(description="代码修复提供方，例如 rules 或 claude")
    summary: str = Field(description="代码修复摘要")
    root_cause: str = Field(description="代码层根因")
    changed_files: list[str] = Field(description="实际检测到的修改文件")
    file_changes: list[CodeRepairFileChange] = Field(description="修改后文件内容")
    diff_text: str = Field(description="统一 Diff")
    tests_passed: bool = Field(description="独立测试是否通过")
    test_command: list[str] = Field(description="独立验证实际运行的测试命令")
    test_output: str = Field(description="基线测试和修复后测试输出")
    agent_report: CodeRepairAgentReport | None = Field(default=None, description="Agent 的结构化修复报告")


class CodeRepairCreate(BaseModel):
    """创建代码修复任务。"""

    requested_by: str = Field(min_length=1, max_length=120, description="发起人")
    instructions: str | None = Field(default=None, max_length=4000, description="可选的人工修复要求")
    source_profile: str = Field(
        default="demo-buffer-bug",
        min_length=1,
        max_length=120,
        description="后端允许使用的源码模板名称",
    )


class CodeRepairApprovalRequest(BaseModel):
    """批准代码补丁。"""

    approved_by: str = Field(min_length=1, max_length=120, description="审核人")
    note: str | None = Field(default=None, max_length=1000, description="审批备注")


class CodeRepairRejectionRequest(BaseModel):
    """拒绝代码补丁。"""

    rejected_by: str = Field(min_length=1, max_length=120, description="拒绝人")
    reason: str = Field(min_length=1, max_length=1000, description="拒绝原因")


class PullRequestPublishRequest(BaseModel):
    """发布 GitHub Pull Request。"""

    published_by: str = Field(min_length=1, max_length=120, description="发布人")
    title: str | None = Field(default=None, max_length=240, description="可选 PR 标题")
    body: str | None = Field(default=None, max_length=8000, description="可选 PR 正文")


class CodeRepairJobRead(BaseModel):
    """代码修复任务完整详情。"""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(description="代码修复任务 ID")
    incident_id: str = Field(description="关联的 Incident ID")
    status: CodeRepairStatus = Field(description="代码修复任务状态")
    provider: str | None = Field(description="代码修复提供方")
    requested_by: str = Field(description="任务发起人")
    instructions: str | None = Field(description="人工修复要求")
    source_profile: str = Field(description="使用的源码模板")
    summary: str | None = Field(description="修复摘要")
    root_cause: str | None = Field(description="代码层根因")
    changed_files: list[str] = Field(description="修改文件列表")
    diff_text: str | None = Field(description="统一 Diff")
    test_command: list[str] = Field(description="独立验证命令")
    test_output: str | None = Field(description="测试输出")
    tests_passed: bool | None = Field(description="测试是否通过")
    approved_by: str | None = Field(description="补丁审核人")
    approval_note: str | None = Field(description="审批备注")
    approved_at: datetime | None = Field(description="批准时间")
    branch_name: str | None = Field(description="发布 PR 时创建的分支")
    pull_request_url: str | None = Field(description="Pull Request 地址")
    pull_request_number: int | None = Field(description="Pull Request 编号")
    error_message: str | None = Field(description="失败错误信息")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")
    finished_at: datetime | None = Field(description="任务结束时间")
    events: list[RepairEventRead] = Field(default_factory=list, description="代码修复事件时间线")


class CodeRepairJobSummary(BaseModel):
    """嵌入 Incident 详情中的代码修复任务摘要。"""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(description="代码修复任务 ID")
    status: CodeRepairStatus = Field(description="任务状态")
    provider: str | None = Field(description="修复提供方")
    summary: str | None = Field(description="修复摘要")
    changed_files: list[str] = Field(description="修改文件列表")
    tests_passed: bool | None = Field(description="测试是否通过")
    pull_request_url: str | None = Field(description="Pull Request 地址")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class IncidentRead(BaseModel):
    """Incident 完整详情。"""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(description="Incident ID")
    fingerprint: str = Field(description="告警去重指纹")
    service_name: str = Field(description="故障服务名称")
    alert_type: str = Field(description="告警类型")
    severity: Severity = Field(description="严重程度")
    status: IncidentStatus = Field(description="Incident 当前状态")
    alert_payload: dict[str, Any] = Field(description="原始告警数据")
    evidence: dict[str, Any] | None = Field(description="后端收集的运行证据")
    diagnosis: dict[str, Any] | None = Field(description="结构化诊断结果")
    remediation_plan: dict[str, Any] | None = Field(description="修复计划")
    verification: dict[str, Any] | None = Field(description="修复后验证结果")
    error_message: str | None = Field(description="流程失败错误信息")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")
    resolved_at: datetime | None = Field(description="解决时间")
    events: list[IncidentEventRead] = Field(default_factory=list, description="Incident 事件时间线")
    tool_executions: list[ToolExecutionRead] = Field(default_factory=list, description="工具执行审计记录")
    repair_jobs: list[CodeRepairJobSummary] = Field(default_factory=list, description="关联的代码修复任务")


class AlertAccepted(BaseModel):
    """告警接收结果。"""

    incident: IncidentRead = Field(description="新建或命中的 Incident")
    deduplicated: bool = Field(description="是否命中重复告警并复用现有 Incident")


class ApprovalRequest(BaseModel):
    """批准高风险运行时修复。"""

    approved_by: str = Field(min_length=1, max_length=120, description="审批人")
    note: str | None = Field(default=None, max_length=1000, description="审批备注")


class RejectionRequest(BaseModel):
    """拒绝高风险运行时修复。"""

    rejected_by: str = Field(min_length=1, max_length=120, description="拒绝人")
    reason: str = Field(min_length=1, max_length=1000, description="拒绝原因")


class FaultInjectionRequest(BaseModel):
    """向演示服务注入受控故障。"""

    fault_type: Literal["service_unavailable", "deploy_regression", "high_latency"] = Field(
        description="故障类型：服务不可用、部署回归或高延迟"
    )


class RuntimeState(BaseModel):
    """演示服务当前运行状态。"""

    service_name: str = Field(default="demo-api", description="服务名称")
    running: bool = Field(default=True, description="服务是否正在运行")
    version: str = Field(default="v1-stable", description="当前版本")
    error_rate: float = Field(default=0.0, description="错误率")
    latency_ms: int = Field(default=50, description="延迟，单位毫秒")
    active_fault: str | None = Field(default=None, description="当前注入的故障类型")
