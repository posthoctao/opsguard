# Phase 3：隔离式代码修复

## 目标

在不向运行时诊断 Agent 开放任意 Shell、源码仓库、Docker 或 GitHub 权限的前提下，增加代码级修复能力。

## 信任边界

```text
后端
- Incident 数据库
- Docker Runtime 权限
- 可选 GitHub 凭证

Repair Worker
- 仅在 Claude 模式下持有 Anthropic 凭证
- 只读打包源码模板
- 每个任务独立可写工作区
- 无 Docker Socket
- 无 GitHub 凭证

验证服务
- 无 Anthropic、Docker 或 GitHub 凭证
- 仅内部网络
- 工作区只读挂载
- 固定 pytest 命令

Claude 代码 Agent
- 仅限工作区的文件工具
- 受限制的验证命令
- 禁止非沙箱 Bash
- Bash 禁止联网
```

## 任务生命周期

```text
QUEUED
→ RUNNING
→ PATCH_READY
→ APPROVED / REJECTED
→ PUBLISHED（可选）
```

在工作区准备、Agent 执行、路径策略校验或独立测试阶段失败，任务都会进入 `FAILED`。

## 验证规则

只有同时满足以下条件，补丁才会进入 `PATCH_READY`：

1. 基线回归测试必须失败。
2. 修复至少修改一个白名单中的业务源码文件。
3. 测试和配置清单必须逐字节保持不变。
4. 不允许引入二进制文件。
5. 服务端固定配置的测试命令必须通过。
6. 必须持久化统一 Diff 和完整的修改后文件内容。

## 为什么补丁审批必须独立

运行时恢复审批授权的是回滚等操作；补丁审批授权的是源码修改。两者分离，可以避免紧急故障处理被误认为拥有修改代码仓库的权限。
