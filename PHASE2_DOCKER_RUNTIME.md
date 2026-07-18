# Phase 2：真实 Docker Runtime Adapter

这一阶段用 Docker SDK Adapter 替代纯模拟的 HTTP 修复路径，使后端能够检查并操作一个明确加入白名单的演示容器。

## 主要变化

- 新增 `app/runtime/docker.py`。
- 新增 `RUNTIME_BACKEND=docker`。
- 在 `compose.yaml` 中把 Docker Socket 挂载到后端容器。
- 每次 Docker 操作前检查固定容器名和受管标签。
- 支持真实容器检查、日志收集、停止、重启、删除和重建。
- 部署回归和回滚改为通过受控版本环境变量重建容器。
- 修复后增加 Docker 健康验证。
- 使用 Fake Docker Client 增加 Adapter 单元测试。

## 故障行为

| 场景 | 故障注入 | 修复操作 |
|---|---|---|
| `service_unavailable` | 停止受管容器 | Docker 重启 |
| `high_latency` | 修改演示服务运行状态 | Docker 重启并重置进程状态 |
| `deploy_regression` | 以 `v2-buggy` 重建容器 | 审批后以 `v1-stable` 重建 |

## 安全边界

模型不能选择以下内容：

- Docker 容器名
- Docker 镜像
- Docker 网络
- 主机端口
- 受管标签
- `v1-stable` 以外的回滚目标

这些值全部由服务端配置。若容器不包含 `com.incident-ai.managed=true`，Runtime 会拒绝操作。

## 重要限制

挂载 `/var/run/docker.sock` 会让后端进程拥有较高的 Docker Daemon 权限。这种方式适合本地求职演示，不适合直接用于生产环境。生产版本应使用权限范围更小的控制服务或其他隔离边界，避免直接暴露 Daemon Socket。
