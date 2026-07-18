# 智能故障诊断与安全修复后端

这是一个事件驱动的 **AI 后端系统**，用于服务故障诊断、策略控制的运行时修复、人工审批、确定性恢复验证，以及隔离式代码修复。

项目重点不是制作聊天机器人或单一运维脚本，而是展示如何把大模型接入一个有状态、可审计、受权限约束的后端系统。大模型负责不确定性的故障分析与代码推理；后端代码负责状态管理、权限判断、实际执行、测试验证和审计记录。

> 说明：为保证 API、数据库和程序逻辑稳定，状态值、动作名、字段名等机器可读常量继续使用英文，例如 `RESOLVED`、`restart_service`。所有面向面试官和使用者的文档、接口说明、提示词、事件信息和命令行输出均已中文化。

## 当前架构

```text
Prometheus / 测试故障注入器
              |
              v
          FastAPI 后端
              |
     +--------+---------+
     |                  |
运行时故障流程        代码修复流程
     |                  |
Claude / 规则诊断     隔离式修复 Worker
     |              Claude / 规则代码 Agent
策略引擎                 |
     |               受保护工作区
Docker 运行时             |
     |               独立 pytest 验证
恢复验证                 |
                    人工审核补丁
                         |
                   可选发布 GitHub PR
```

## Phase 3 新增能力

- 独立的 `repair-worker` 服务，不挂载 Docker Socket，也不持有 GitHub Token。
- 仅允许后端白名单中的源码模板复制到独立可写工作区。
- 支持 Claude Agent SDK，无法调用时也可使用确定性规则模式完成演示。
- 限制文件访问和 Bash 命令，启用 SDK 沙箱，禁止非沙箱命令，并禁止修改测试文件。
- 基线测试和修复后测试都由普通 Python 代码独立执行，不采信 Agent 自己声称的测试结果。
- 修复任务及完整事件时间线持久化到数据库。
- 经过测试的补丁必须单独人工审批。
- 补丁批准后可由后端发布 GitHub Pull Request。
- GitHub 凭证始终保留在后端，不进入 Agent 边界。

## 两条核心工作流

### 运行时故障修复

```text
接收告警
→ 收集运行证据
→ AI 结构化诊断
→ 服务端策略评估
→ 自动执行低风险操作，或等待人工审批
→ 执行 Docker 操作
→ 确定性健康验证
→ RESOLVED / ESCALATED
```

### 代码修复

```text
运行时 Incident 进入终态
→ 创建代码修复任务
→ 复制隔离源码
→ 基线测试失败
→ 受约束的代码 Agent 修改源码
→ 检查受保护文件
→ 独立测试通过
→ PATCH_READY
→ 人工批准或拒绝
→ 可选发布 PR
```

运行时回滚与代码修改是两个独立决定。恢复服务可用性，不代表系统自动获得修改源码仓库的权限。

## 技术栈

- Python 3.12
- FastAPI
- SQLAlchemy + SQLite
- Claude Agent SDK
- Docker SDK + Docker Compose
- Pydantic 结构化输出
- httpx
- pytest
- 可选的 GitHub Git Data API 集成

## 使用 Docker 快速启动

### 1. 创建环境配置

```bash
cp .env.example .env
```

默认配置使用确定性的规则诊断和规则代码修复，因此没有 API Key 也可以运行完整演示。

### 2. 启动全部服务

```bash
docker compose up --build
```

服务地址：

- 后端 API：`http://localhost:8000`
- Swagger 接口文档：`http://localhost:8000/docs`
- 故障演示服务：`http://localhost:8081`
- 代码修复 Worker：内部端口 `8090`
- 无密钥验证服务：仅内部网络端口 `8100`

### 3. 运行自动修复演示

```bash
docker compose exec backend python scripts/run_demo.py service_unavailable \
  --base-url http://127.0.0.1:8000
```

### 4. 运行“回滚 + 代码修复”演示

```bash
docker compose exec backend python scripts/run_repair_demo.py \
  --base-url http://127.0.0.1:8000
```

预期核心结果：

```text
运行时 Incident：WAITING_FOR_APPROVAL → RESOLVED
代码修复：QUEUED → RUNNING → PATCH_READY → APPROVED
独立测试：通过
修改文件：sample_service/cache.py
```

## 启用 Claude Agent SDK

在 `.env` 中设置：

```env
AI_PROVIDER=claude
REPAIR_AGENT_PROVIDER=claude
ANTHROPIC_API_KEY=你的_API_Key
```

然后重新构建：

```bash
docker compose up --build
```

故障诊断 Agent 不拥有任何工具。代码修复 Agent 只在隔离式 Repair Worker 中运行，并且仅能访问独立工作区。

## 可选：发布 GitHub Pull Request

PR 发布默认关闭。配置：

```env
GITHUB_PR_ENABLED=true
GITHUB_TOKEN=你的细粒度令牌
GITHUB_REPOSITORY=owner/repository
GITHUB_BASE_BRANCH=main
```

补丁达到 `APPROVED` 后调用：

```text
POST /api/v1/repairs/{repair_job_id}/publish-pr
```

后端会创建 Git Blob、Tree、Commit、Branch 和 Pull Request。Repair Worker 与 Claude 都不会接触 GitHub Token。目标仓库需要包含与所选源码模板相同的文件路径。

## 核心 API

### Incident 管理

```text
POST /api/v1/alerts
GET  /api/v1/incidents
GET  /api/v1/incidents/{incident_id}
POST /api/v1/incidents/{incident_id}/process
POST /api/v1/incidents/{incident_id}/approve
POST /api/v1/incidents/{incident_id}/reject
```

### 代码修复管理

```text
POST /api/v1/incidents/{incident_id}/repairs
GET  /api/v1/repairs
GET  /api/v1/repairs/{repair_job_id}
POST /api/v1/repairs/{repair_job_id}/approve
POST /api/v1/repairs/{repair_job_id}/reject
POST /api/v1/repairs/{repair_job_id}/publish-pr
```

### 故障演示运行时

```text
GET  /api/v1/runtime/state
POST /api/v1/runtime/faults
POST /api/v1/runtime/reset
```

## 安全边界

### 故障诊断 Agent

- 只接收告警和后端已经收集的证据。
- 工具集合为空。
- 不能执行 Shell 命令，也不能读取文件。
- 只能输出结构化诊断建议，不能声称已经执行修复。

### 运行时执行器

- 容器名、镜像、网络和标签全部由服务端固定配置。
- 不接受模型生成的任意 Shell 命令。
- 完整记录 `AUTHORIZED → EXECUTING → SUCCEEDED / FAILED`。
- 只有独立验证通过后才把 Incident 标记为已解决。

### 代码修复 Worker

- 作为独立容器运行，不挂载 Docker Socket。
- 不持有 GitHub 凭证。
- 只复制一个由后端白名单指定的源码模板。
- 禁止修改测试、依赖、CI 和非白名单源码。
- Bash 仅允许 pytest、compileall 和 ruff 验证命令。
- 禁止非沙箱命令和 Bash 网络访问。
- 基线与最终测试发送给独立验证服务，该服务没有模型、Docker 或 GitHub 凭证。

### 无密钥验证服务

- 位于无外网出口的 Docker 内部网络。
- 只接收服务端生成的修复任务 ID。
- 以只读方式挂载工作区，并在清理后的环境中运行固定 pytest 命令。
- 不持有 Anthropic、Docker 或 GitHub 凭证。

### PR 发布器

- 仅在补丁明确通过人工审批后，由后端执行。
- 使用后端持有的凭证。
- 只能发布已经保存在已批准 Repair Job 中的文件内容。

## 状态和动作说明

为保持代码接口稳定，以下值继续使用英文：

| 机器状态 | 中文含义 |
|---|---|
| `OPEN` | 已创建，等待处理 |
| `COLLECTING_EVIDENCE` | 正在收集证据 |
| `DIAGNOSING` | 正在诊断 |
| `PLANNING` | 正在评估修复计划 |
| `WAITING_FOR_APPROVAL` | 等待人工审批 |
| `REMEDIATING` | 正在执行修复 |
| `VERIFYING` | 正在验证恢复结果 |
| `RESOLVED` | 已解决并验证 |
| `ESCALATED` | 已升级人工处理 |
| `FAILED` | 流程执行失败 |

| 机器动作 | 中文含义 |
|---|---|
| `restart_service` | 重启服务 |
| `rollback_deployment` | 回滚部署 |
| `no_safe_action` | 没有可安全自动执行的操作 |

## 当前定位

本项目是一个可运行、可测试、可演示的工程化 AI 后端 MVP，适合用于展示：

- Agent 与传统后端逻辑的职责边界
- 事件驱动 API
- 状态机与数据库持久化
- 工具白名单和策略引擎
- Human-in-the-loop
- 真实 Docker 操作
- 确定性恢复验证
- 隔离式代码修复
- 审计日志与可追踪性

它仍然是求职演示系统，不应直接作为生产环境的自动运维平台使用。
