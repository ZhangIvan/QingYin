# QingYin 模块 22：SaaS 空间与多租户隔离

版本：v0.2
目标：让一家公司在 QingYin 中安全地为不同部门、业务线、项目组或客户交付团队建立独立空间，同时保持公司级治理、统一账务和可控运营。

## 1. 层级与资源归属

```text
Platform
  -> Organization（公司租户）
      -> Workspace（部门/业务线/团队隔离空间）
          -> Project（应用或产品）
              -> Environment（dev/test/staging/prod）
                  -> API Key / Service Account / Session
```

- `Organization` 是合同、企业身份、公司级账务和全局安全策略边界。
- `Workspace` 是默认的资源和数据隔离边界。它拥有成员、角色、项目、环境、预算、Provider allow-list、数据地域、保留策略、质量报告和审计视图。
- `Project` 服务于一个应用；`Environment` 将开发、测试与生产隔开。
- 任意 session、ticket、lease、缓存对象、用量事件、质量快照、审计事件和路由决策都必须能解析为 `organization_id + workspace_id`。

## 2. 成员、角色与委派

| 角色 | 范围 | 关键权限 |
| --- | --- | --- |
| Organization Owner | 公司 | 创建/冻结 Workspace、公司级账务、SSO、全局策略 |
| Organization Admin | 公司 | 管理成员、Provider 允许范围、跨 Workspace 汇总 |
| Workspace Admin | 单空间 | 项目、成员、预算、策略草稿、空间级审计 |
| Workspace Developer | 项目/环境 | API Key、会话调试、受限用量查看 |
| Workspace Analyst | 单空间 | 质量、容量、会话和报表只读 |
| Workspace Billing | 单空间 | 预算、账务、导出和修正申请 |
| Platform Support | 临时委派 | 仅经 break-glass 审批的脱敏诊断访问 |

权限判定必须同时满足：主体属于 Organization、拥有 Workspace membership、资源在授权 scope 中。公司级角色不自动拥有受限原始数据读取权；跨空间操作必须显式声明目标 Workspace、理由和审计。

企业身份支持 OIDC/SAML 单点登录；成员与组同步使用 SCIM 或等价受控同步。API Key 与 Service Account 只能绑定一个 Workspace 或更窄的 Project/Environment，不能作为“全公司万能密钥”。

## 3. 强制隔离规则

| 边界 | 强制规则 |
| --- | --- |
| 认证/授权 | 每次请求由凭证解析 Workspace；客户端 body 不能覆盖该上下文 |
| 数据库 | 所有租户数据带 Organization/Workspace 主键与索引；查询执行行级/等价强制过滤，不仅依赖应用层 where 条件 |
| 缓存与限流 | key 前缀包含 Organization/Workspace/Environment；禁止跨空间复用 session、token bucket、idempotency 或 TTS cache |
| 对象与备份 | 路径、加密上下文、访问策略绑定 Workspace；导出和恢复按空间授权 |
| Provider | Organization 可定义总允许范围；Workspace 只能收紧 Provider、地域、音色、预算与 Direct 能力 |
| 路由/容量 | 容量卡可在公司共享，但准入、预算、并发和质量门按 Workspace 结算与审计 |
| 账务/质量/审计 | 默认按 Workspace 聚合；Organization 汇总需具备权限，绝不暴露其他空间原始数据 |
| 网络与日志 | trace 带 Workspace ID（受控）；日志检索、Support 诊断和下载遵循 Workspace RBAC |

默认使用共享基础设施上的逻辑强隔离。对高合规/大客户空间，可升级为独立加密密钥、独立 Provider 账户、专用 Worker 池、专属 Edge 或独立地域部署；升级不改变公开 API。

## 4. Workspace 生命周期

```text
draft -> active -> suspended -> archived -> pending_delete -> deleted
```

- `draft`：完成地域、预算、管理员、数据策略与 Provider 允许范围配置后才能激活。
- `active`：可创建项目、密钥和会话。
- `suspended`：停止新会话与新密钥，允许管理员、账务和导出处理；已有流按策略 drain。
- `archived`：只读，保留期仍生效。
- `pending_delete`：撤销密钥/ticket、停止任务、执行备份/导出与数据删除审批。
- `deleted`：删除受限业务数据，保留法律/账务所需最小审计依据。

Workspace 转移、合并或拆分是异步高风险 operation：必须预览受影响项目、密钥、缓存、预算、Provider 路由和数据地域，禁止直接改变已存在 session 的归属。

## 5. 管理面与前端契约

管理 API 提供 Workspace 列表、详情、成员、角色、项目、环境、预算、数据策略、Provider 范围、质量摘要、容量摘要、审计和 operation 状态。所有列表由当前 Organization 和 Workspace 上下文过滤。

控制台顶部必须有 Organization/Workspace 上下文选择器。切换后所有导航、搜索、统计、告警、会话、质量、容量、用量和策略都刷新为目标 Workspace 的授权视图；切换不会携带上一个空间的缓存结果或未保存草稿。

## 6. 验收

1. 同一公司两个 Workspace 无法互相读取、修改、搜索、导出或通过缓存命中彼此资源。
2. Workspace 预算/限流/Provider 降级不会影响同 Organization 的其它健康 Workspace，除非命中公司级硬上限。
3. Support 的 break-glass 访问有时限、理由、最小字段、双人审批与不可变审计。
4. SSO/SCIM、Workspace 冻结/删除、跨空间转移、备份恢复、Direct ticket 和质量报告均经过越权与泄漏测试。
