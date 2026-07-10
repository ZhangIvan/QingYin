# QingYin 管理面资源契约清单

版本：v0.2
状态：管理后台实现前 API 覆盖基线
关联：模块 19、21、22、23；`contracts/openapi/qingyin-admin-v1.yaml`

## 1. 使用方式

此清单规定管理后台每个页面可依赖的资源族、读写语义和权限边界。`qingyin-admin-v1.yaml` 已冻结 Workspace、容量、质量、诊断、路由预览与 operation 的首批路径；其余资源在开始对应后端模块前必须按本清单补入同一 OpenAPI 文件，不能以私有 JSON 或直接查日志替代。

所有列表响应均使用 `items`、`next_cursor?`、`request_id`；服务端只接受排序白名单和已声明过滤字段。所有可变资源返回 `resource_version`，所有写操作要求 `Idempotency-Key`、`If-Match`（创建除外）和 `X-QingYin-Change-Reason`。高风险写操作还要求重新认证/短时提升权限与审批引用。

## 2. 资源族与页面覆盖

| 资源族 | 最小路径族 | 核心操作 | 主要页面/模块 | 最低权限 |
| --- | --- | --- | --- | --- |
| 当前上下文 | `GET /v1/admin/context` | 当前 Organization、Workspace、Environment、权限和 feature flags | 全局顶部选择器 | 已登录成员 |
| Workspace | `/workspaces`、`/workspaces/{id}`、`/members` | 列表、创建、详情、成员、冻结/归档 | 空间管理、组织成员 | Org Admin / Workspace Admin |
| Project / Environment | `/workspaces/{id}/projects`、`/projects/{id}/environments` | 创建、编辑、归档、环境切换 | 应用管理 | Workspace Admin |
| Credential | `/api-credentials`、`/service-accounts` | 创建、范围、轮换、撤销、最近使用 | 密钥管理 | Workspace Developer 或更高 |
| Provider | `/provider-snapshots`、`/provider-accounts`、`/provider-probes` | 只读能力、探针、启停申请 | 语音资源、路由策略 | Org Admin / Provider Admin |
| Routing policy | `/routing/policies`、`/versions`、`/preview`、`/publish`、`/rollback` | 草稿、差异、模拟、审批、灰度、回滚 | 路由与策略、版本管理 | Policy Approver |
| Capacity | `/capacity-cards`、`/publish`、`/history` | 查询、创建、评审、发布、失效、比较 | 容量管理 | SRE / Workspace Admin |
| Quality / version | `/quality-reports`、`/model-versions`、`/gates` | 查询趋势、版本比较、质量门结论 | 质量分析、版本管理 | Workspace Analyst |
| Quota / budget / usage | `/quotas`、`/budgets`、`/usage`、`/reconciliations` | 查看、申请、审批、导出、修正申请 | 用量统计、容量管理 | Workspace Billing |
| Session / diagnostic | `/sessions`、`/sessions/{id}`、`/sessions/{id}/diagnostic` | 脱敏列表、详情、诊断快照、受控实时订阅 | 实时监控、会话列表、会话调试 | Developer / Analyst；L4/L5 另授权 |
| Audit / incident | `/audit-events`、`/incidents` | 查询、过滤、关联 operation/diagnostic、处置确认 | 审计日志、告警中心 | Audit Reader / On-call |
| Operation / approval | `/operations`、`/approvals` | 轮询进度、取消、审批、拒绝、审计追踪 | 全局操作抽屉、各变更页面 | 资源对应审批角色 |

## 3. 后台页面不可绕过的服务端规则

- 会话列表和诊断只能返回由当前 Organization/Workspace 显式授权的记录；搜索、cursor、导出和实时订阅同样受此规则约束。
- 质量报告、容量卡、用量和 Provider 健康均返回聚合指标；原始音频、文本、厂商主凭证和无限基数 trace 标签不进入普通页面接口。
- 版本管理至少区分草稿、预览、canary、active、rolled_back；发布/回滚必须形成 `operation` 与 audit event。
- 容量卡只有 `active` 且未过期的实验/配置指纹才能参与 Admission；前端展示的“可用容量”只能来自有效卡与实时水位的组合。
- Workspace 切换必须清空上一个 Workspace 的内存缓存、未提交草稿和订阅；服务端响应仍以鉴权上下文为最终边界。
- 删除、冻结、密钥撤销、Provider 下线、路由发布、预算硬限额变更、L5 捕获和导出均为高风险操作，不能由普通项目 API Key 调用。

## 4. 契约补全门槛

开始某一控制台模块前，相关路径必须具备：schema、枚举、分页/过滤、权限、空态、错误、幂等/并发写规则、审计字段、最小/最大示例，以及前端所需的 loading/permission/operation 状态。未完成该项的页面只能保留在设计稿，不得开始正式接口或前端实现。
