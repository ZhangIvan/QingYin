# QingYin M1：实施 Backlog、CI 门禁与阶段验收包

版本：v0.3
状态：M1-01 至 M1-04 已完成，M1-05 实现与门禁收敛中
关联：M1 Rust 核心骨架、Fixture/MockProvider 规范、模块 08、测试验收与发布计划

## 1. M1 交付边界

M1 是“可测核心骨架”，不是生产发布。它只依赖 MockProvider，完成之后可以证明 QingYin 的公开契约、租户上下文、准入、Relay 会话、取消、计量和观测边界可运行；它不能证明真实 Provider 质量、云端配额、实际机器容量或高可用。

| 需求覆盖 | M1 覆盖方式 | 仍需后续阶段关闭 |
| --- | --- | --- |
| FR-001、FR-003、FR-004、FR-005、FR-008、FR-018、FR-019、FR-026 | MockProvider + golden fixture + Gateway/SDK 兼容测试 | 两个真实 Adapter 与 SDK 实测 |
| FR-002、FR-009、FR-021、FR-022、FR-023 | 简化候选路由、Admission、reservation/outbox、基础 usage | 真实账户配额、成本、完整降级和对账 |
| FR-006、FR-007、FR-015、FR-020、FR-024、FR-028 | policy hard deny、opaque ticket、Mock capability snapshot、隔离与安全测试 | Local Worker、Direct、真实 Provider probe、恢复演练 |
| NFR-001 至 NFR-006、NFR-010 至 NFR-014、NFR-016 | 契约/状态/安全/韧性测试和开发性能 smoke | 容量卡实测、生产压测、审计与高可用证据 |

## 2. 工作包与依赖

| ID | 工作包 | 前置 | 后续/并行关系 | 完成证据 |
| --- | --- | --- | --- | --- |
| M1-01 | Workspace bootstrap：crate 边界、依赖规则、错误处理、统一 lint 配置 | 无 | 已与 M1-02 在 PR #4 合并 | workspace 依赖图审查；最小编译/格式检查 |
| M1-02 | Canonical types/contract：ID、事件、错误、DTO、状态机、schema binding | M1-01 | 完成后启动 M1-03 | contract fixture 单测、OpenAPI/AsyncAPI 对照 |
| M1-03 | Durable/Ephemeral State：Repository trait、事务、reservation、outbox、TTL 与内存 test double | M1-01、M1-02 | 已通过 PR #15 合并 | 状态、事务、TTL、隔离和幂等单测；真实 Postgres/Redis 留待 R2 |
| M1-04 | Security context：principal、scope、ticket、日志脱敏 | M1-03 | 已通过 PR #16 合并 | 撤销、单次 ticket、跨 Workspace 与 log redaction 测试；HTTP credential verifier 留待 M1-07 |
| M1-05 | Admission：六门 snapshot、许可、reservation、renew、release/settle/reclaim、retry-after | M1-04 | 实现与门禁收敛中；完成后启动 M1-06 | 全门 allowed/rejected、补偿、精确 TTL、重复/冲突终态、租户隔离与竞态测试 |
| M1-06 | Provider Runtime：trait、registry、MockProvider/profile、错误映射 | M1-05 | 完成后启动 M1-07 | Provider Contract Suite 全通过 |
| M1-07 | Control Gateway：capabilities、create/get/cancel session、幂等、审计 | M1-02 至 M1-06 | 完成后可分别启动 M1-08、M1-09、M1-10 | HTTP contract/integration fixtures；无 Provider 凭证泄漏 |
| M1-08 | Relay Streams：ASR WS、TTS WS、bounded channels、cancel/timeout/slow consumer | M1-06、M1-07 | 可与 M1-09、M1-10 使用独立 PR 并行 | streaming fixtures、资源释放与内存边界 smoke |
| M1-09 | One-shot TTS HTTP：首字节语义、metadata、stream error 记录 | M1-06、M1-07 | 可与 M1-08、M1-10 使用独立 PR 并行 | `tts.http.happy` 及首字节前/后失败 fixture |
| M1-10 | Usage/observability：outbox consumer、usage event、metrics、trace、健康检查 | M1-03、M1-05、M1-07 | 可与 M1-08、M1-09 使用独立 PR 并行 | 使用去重、审计关联、低基数标签与 trace 断言 |
| M1-11 | CI/Release evidence：schema lint、fixtures、测试环境、SBOM/依赖/secret 检查 | M1-01 至 M1-10 | 门禁持续建设；最终验收等待 M1-10 | 绿色 CI、制品清单、变更记录和验收报告 |

`M1-07` 之前不创建对外可用 Gateway；`M1-08/09` 之前不宣称“支持流式”；`M1-11` 不通过时不允许合并任何公开契约或状态变更。

执行 Issue：M1-03 [#5](https://github.com/ZhangIvan/QingYin/issues/5)、M1-04 [#6](https://github.com/ZhangIvan/QingYin/issues/6)、M1-05 [#7](https://github.com/ZhangIvan/QingYin/issues/7)、M1-06 [#8](https://github.com/ZhangIvan/QingYin/issues/8)、M1-07 [#9](https://github.com/ZhangIvan/QingYin/issues/9)、M1-08 [#10](https://github.com/ZhangIvan/QingYin/issues/10)、M1-09 [#11](https://github.com/ZhangIvan/QingYin/issues/11)、M1-10 [#12](https://github.com/ZhangIvan/QingYin/issues/12)、M1-11 [#13](https://github.com/ZhangIvan/QingYin/issues/13)。

## 3. Definition of Ready 与 Definition of Done

每个工作包开始前必须具备：关联需求 ID、对应契约 operation/event、fixture ID、错误/权限/隐私影响、状态写入与 release 语义、指标、配置项和依赖 work package。缺任一项时不得以“实现中再决定”进入开发。

每个工作包完成需同时满足：

1. 公共类型、API 或事件的变更已更新 OpenAPI/AsyncAPI、模块 12 和 fixture。
2. 正常、失败、取消、重复请求/竞态和越权路径均有自动化测试。
3. 错误使用 canonical code；日志、trace、metric、数据库与 cache 均不含密钥、ticket、原始音频或完整文本。
4. 资源获得和释放可由持久状态、指标和测试断言三者交叉验证。
5. 数据库 migration 可向前执行；不可逆或破坏性变更带单独恢复/回滚说明。
6. 代码审阅确认没有绕过 Provider trait、Admission、租户上下文或 State Repository。

## 4. CI 门禁

CI 由本地可复现步骤和受限集成步骤组成。默认 CI 不访问公网、不使用真实 Provider 凭证；真实 Sandbox probe 是独立、审批过的工作流。

| 门禁 | 触发范围 | 必须检查 | 拦截条件 |
| --- | --- | --- | --- |
| 格式与静态检查 | 每次变更 | Rust format、lint、禁止不安全依赖/未处理错误、crate 依赖方向 | warning、跨层依赖、禁止 API |
| 协议检查 | `contracts/` 或公开类型变更 | OpenAPI/AsyncAPI schema 解析、引用、示例/fixture、breaking diff | 无效 YAML、破坏 v1 字段/事件、缺少错误或鉴权 |
| 单元/属性测试 | Core/Contract/Admission/Provider/State | 状态机、边界值、未知枚举、序列、限流、映射 | 不稳定、随机种子未固定、断言不足 |
| 集成测试 | Gateway/State/Relay 变更 | 临时 Postgres/Redis、MockProvider、WebSocket、HTTP stream、outbox | 事务、TTL、cancel、慢消费者、越权失败 |
| 隔离与安全 | Auth/State/Config/日志变更 | Workspace 越权、ticket race、idempotency、secret scan、redaction | 跨空间读写、token/secret 出现在日志或制品 |
| 依赖与制品 | 任意依赖/发布变更 | 锁文件、许可证/漏洞策略、SBOM、镜像/二进制可追溯 | 未批准高风险依赖、不可追溯制品 |
| 性能 smoke | Relay/Admission/Runtime 变更 | 固定合成流、连接/取消、内存不增长、P95 基线 | 明显回归；不将 smoke 结果写成容量 SLA |
| 受限 sandbox probe | 新/变更真实 Adapter | 模块 09 probe、成本/配额/地域/认证/取消记录 | 探针不通过却尝试启用路由 |

任何接口兼容性差异、fixture 更新或测试基线调整都必须在 PR/变更记录里说明“为何不破坏 v1”；没有说明的 baseline 放宽不允许合并。

## 5. 测试环境与数据原则

| Profile | 状态依赖 | Provider | 可用于 | 禁止用于 |
| --- | --- | --- | --- | --- |
| `unit` | 内存 fake、虚拟时钟 | Scripted MockProvider | 快速类型/策略/状态机测试 | 并发正确性或迁移结论 |
| `integration` | 临时 Postgres + Redis | MockProvider | transaction、TTL、Gateway、WS/HTTP stream | 真实 Provider 能力结论 |
| `sandbox` | 隔离的非生产状态 | 单一已批准 Provider account | Adapter probe/互操作 | 默认 CI、生产流量 |
| `load` | 与目标环境等价的隔离部署 | Mock 或批准 Provider | 容量卡输入、故障注入 | 把单次结果泛化到其它规格 |

所有测试使用 synthetic tenant/workspace/project/environment 和可轮换的测试 secret reference。测试结束后验证 Redis key、活跃 session、reservation、MockProvider 调用记录和对象临时文件均被回收。

## 6. M1 阶段验收包

M1 验收记录必须包含以下可定位证据，而不仅是一句“测试通过”：

- 对应 commit/config/fixture manifest hash、crate 依赖图和构建制品清单。
- 三份接口契约的解析/兼容检查报告，以及 M1 已实现 operation/event 清单。
- MockProvider 7 个 profile、黄金路径 6 项、错误/韧性 12 项的通过记录。
- fake contract suite、ticket 单次消费、Workspace 隔离、cancel 释放、usage/outbox 去重和日志脱敏报告；真实 PostgreSQL/Redis 一致性与恢复作为 R2 强制证据，不能由 fake 代替。
- 固定合成负载下的运行时 smoke：连接、首事件、TTS 首字节、cancel、内存/FD/任务收敛趋势；不填写未经压测推导的并发数。
- 已知限制：仅 mock、无真实云/本地模型、无 Direct、无 Realtime runtime、无生产容量/SLO 承诺。

## 7. 阶段退出与下一阶段入口

只有当 M1-01 至 M1-11 全部关闭、无 P0 契约/隔离/资源泄漏问题、验收包完整时，才能进入 M2。M2 的第一个变更只能是一个已完成 Module 09 sandbox probe 的 Provider Adapter；第二 Provider、Direct、Local Worker、LLM 与后台页面均不允许借 M1 验收名义提前进入。
