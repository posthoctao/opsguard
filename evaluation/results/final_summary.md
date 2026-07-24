# 最小评测结果

- 评测时间：2026-07-18T06:29:35-04:00
- 后端地址：`http://127.0.0.1:8001`
- 运行时故障样本数：9
- 代码修复样本数：2

## 总体指标

| 指标 | 结果 |
|---|---:|
| 运行时完整成功率 | 9/9 (100.0%) |
| 诊断完成率 | 9/9 (100.0%) |
| 修复动作选择准确率 | 9/9 (100.0%) |
| 审批流程正确率 | 9/9 (100.0%) |
| 修复后验证通过率 | 9/9 (100.0%) |
| 平均 Incident 处理时间 | 20.88 秒 |
| 代码修复完整成功率 | 2/2 (100.0%) |
| 代码修复测试通过率 | 2/2 (100.0%) |
| 修改范围合规率 | 2/2 (100.0%) |
| 平均代码修复时间 | 53.45 秒 |

## 分场景结果

| 场景 | 次数 | 完整成功率 | 动作准确率 | 平均处理时间 |
|---|---:|---:|---:|---:|
| `service_unavailable` | 3 | 100.0% | 100.0% | 19.34 秒 |
| `deploy_regression` | 3 | 100.0% | 100.0% | 20.01 秒 |
| `high_latency` | 3 | 100.0% | 100.0% | 23.27 秒 |

## 运行明细

| 类型 | 场景 | 序号 | 成功 | 最终状态 | 动作/测试 | 耗时 |
|---|---|---:|---|---|---|---:|
| Incident | `service_unavailable` | 1 | 是 | `RESOLVED` | `restart_service` | 19.003 秒 |
| Incident | `service_unavailable` | 2 | 是 | `RESOLVED` | `restart_service` | 18.969 秒 |
| Incident | `service_unavailable` | 3 | 是 | `RESOLVED` | `restart_service` | 20.047 秒 |
| Incident | `deploy_regression` | 1 | 是 | `RESOLVED` | `rollback_deployment` | 20.845 秒 |
| Incident | `deploy_regression` | 2 | 是 | `RESOLVED` | `rollback_deployment` | 20.408 秒 |
| Incident | `deploy_regression` | 3 | 是 | `RESOLVED` | `rollback_deployment` | 18.79 秒 |
| Incident | `high_latency` | 1 | 是 | `RESOLVED` | `restart_service` | 18.574 秒 |
| Incident | `high_latency` | 2 | 是 | `RESOLVED` | `restart_service` | 23.799 秒 |
| Incident | `high_latency` | 3 | 是 | `RESOLVED` | `restart_service` | 27.443 秒 |
| Code Repair | `demo_buffer_bug` | 1 | 是 | `PATCH_READY` | 测试通过 | 48.319 秒 |
| Code Repair | `demo_buffer_bug` | 2 | 是 | `PATCH_READY` | 测试通过 | 58.576 秒 |

## 说明

- 完整成功要求：诊断结果存在、动作选择正确、审批路径正确、最终状态为 `RESOLVED`，且确定性验证通过。
- 代码修复成功要求：任务进入 `PATCH_READY`、独立测试通过，且只修改 `sample_service/cache.py`。
- 本评测规模较小，只用于求职项目的可复现性验证，不代表生产环境基准测试。
