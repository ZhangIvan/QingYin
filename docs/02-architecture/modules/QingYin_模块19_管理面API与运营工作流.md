# QingYin 模块 19：管理面 API 与运营工作流

版本：v0.2
目标：为后续控制台提供稳定、脱敏、可授权的管理数据契约，并把高风险变更收敛为可预览、审批、审计和回滚的工作流。

## 1. 管理资源

| 资源 | 关键操作 | 禁止暴露 |
| --- | --- | --- |
| Organization / Workspace / Project / Environment | 创建、归档、成员、角色、数据策略 | 其他租户或未授权 Workspace 信息 |
| API Key / Service Account | 创建、范围、轮换、撤销、最后使用 | 密钥明文的再次读取 |
| Provider Snapshot / Account Ref | 查看能力、探针结果、状态、启停 | Provider 主凭证、授权 URL |
| Policy Version | 草稿、预览、审批、灰度、回滚 | 未授权租户样本、完整用户文本 |
| Capacity Card | 创建、评审、发布、失效、历史比较 | 不相关环境敏感拓扑 |
| Model Version / Quality Report | 查看版本、评测、趋势、对比、质量门结论 | 原始受限样本、未授权人工标注 |
| Quota / Budget | 查看、申请、审批、冻结 | 内部成本系数（无权限时） |
| Usage / Reconciliation | 查看、导出、差异、修正申请 | 其他租户账务与原始音频 |
| Audit / Incident | 查询、关联诊断、确认处置 | 密钥、ticket、完整受限内容 |

## 2. Admin API 约定

管理 API 使用独立 OpenAPI 文档和 `/v1/admin` 命名空间，要求 Service Account 或受控管理会话。所有写操作携带 `Idempotency-Key`、预期资源版本和变更原因；资源版本冲突必须返回可操作错误，不做最后写入覆盖。

长时间操作（探针、容量计算、导出、备份恢复、批量轮换）创建可查询的 `operation` 资源，状态为 `queued|running|succeeded|failed|cancelled`，并记录输入摘要、进度、结果引用、执行主体和审计 ID。它们可使用异步任务系统，但永不参与实时音频链路。

## 3. 高风险工作流

| 工作流 | 强制步骤 | 审批/回滚 |
| --- | --- | --- |
| 启用 Provider | 模块 09 探针 -> 能力快照 -> preview -> canary | 管理员审批；关闭路由权重 |
| 创建/冻结 Workspace | 组织策略校验 -> Workspace 管理员/预算/地域设置 -> 审计 | Organization 管理员审批；冻结新会话 |
| 发布路由策略 | schema/硬约束检查 -> 影响预览 -> canary -> 观察 | 双人审批；回滚上一稳定版本 |
| 发布容量卡/提高额度 | 输入来源校验 -> 压测 -> N+1 检查 -> 影响预览 | SRE/管理员审批；下调旧额度 |
| 轮换密钥 | 新引用就绪 -> 双密钥期 -> 验证 -> 撤销旧引用 | 安全角色审批；仅回滚新建连 |
| 账务修正/预算变更 | 差异证据 -> 影响预览 -> 审批 -> 差分事件 | 财务/管理员审批；追加反向修正 |
| 提升模型/Provider 质量权重 | 质量报告 -> 基线比较 -> 路由模拟 -> canary | 模型/质量管理员审批；回滚上一权重 |
| 紧急冻结 | 触发告警/人工事件 -> 限制范围 -> 审计 | 值班角色可执行；事后复核 |

## 4. 前端数据契约

控制台只读取当前 Organization/Workspace 授权范围内的聚合数据：Provider 健康/能力、容量水位、会话统计、用量状态、质量报告/趋势、策略差异、操作进度和审计摘要。所有列表 API 支持 cursor 分页、服务端过滤、排序白名单和最小字段投影；不将完整日志、原始评测样本或音频塞入列表响应。

页面状态以资源状态机驱动：Provider `candidate|sandbox_verified|canary|enabled|degraded|open|retired`，容量卡 `draft|review|active|stale|retired`，策略 `draft|previewed|canary|active|rolled_back`，operation `queued|running|succeeded|failed|cancelled`。这组状态是前端设计稿的唯一状态来源。

## 5. 权限与审计

读取、创建、审批、发布、回滚、冻结、导出和查看受限诊断是独立权限。任何变更都记录 actor、角色、资源、前后版本/hash、原因、审批链、trace/operation ID 和结果。高风险操作需要重新认证或短时提升权限，并禁止通过普通 API Key 执行。

## 6. 验收

- 管理面越权、并发修改、重复提交、失败重试、操作取消和回滚均有确定行为。
- 控制台所需的实体、状态、聚合字段、权限与空/失败状态均由 API 契约提供，不依赖爬日志或厂商私有字段。
- 所有 Provider、策略、容量、预算、密钥和账务变更可回溯到审批与审计记录。
