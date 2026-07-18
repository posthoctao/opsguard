# Clean-room 独立重写说明

本仓库是一个以后端为核心的全新实现，没有复制参考教学项目中的源代码文件。

## Phase 1 已完成目标

- FastAPI 告警接收 API
- SQLite Incident 持久化
- 显式 Incident 状态机
- 告警指纹与去重
- 结构化诊断接口
- 可选 Claude Agent SDK 诊断提供方
- 用于本地测试的确定性规则提供方
- 服务端动作白名单和参数校验
- 高风险回滚人工审批
- 独立工具执行审计记录
- 修复后的确定性验证
- 内存与 HTTP Runtime Adapter
- 独立故障注入演示服务
- Docker Compose 配置
- 自动化工作流测试

## 第一阶段有意暂缓的内容

- PostgreSQL 与 Alembic 迁移
- Redis / Celery Worker 拆分
- Prometheus Alertmanager Webhook 兼容
- 真实 Docker / Kubernetes Runtime Adapter
- GitHub 代码修复 PR
- Dashboard
- 评测数据集和指标报告

这些功能在第一阶段暂缓，是为了优先展示 AI 后端架构，而不是堆叠基础设施。后续 Phase 2 和 Phase 3 已逐步补充真实 Docker Runtime 与隔离式代码修复。
