# QingYin 工程实施总计划与 GitHub 交付治理

版本：v0.3
状态：实施基线；[DEC-20260829-001](QingYin_DEC-20260829-001_单维护者合并治理.md) 为 `PROPOSED / effective=PENDING`
关联：系统设计目录、设计冻结审阅、M1 核心骨架、M1 Backlog、CI 门禁与 DEC-20260829-001

## 0. 决策优先级与过渡边界

单维护者 self-merge 路径只有在 DEC-20260829-001 变为 `ACTIVE` 后才是本仓库的常规合并规则。在此之前，v0.2 第 4 节第 6 步的独立 reviewer/必要审批要求及紧随段落的“高风险变更必须增加第二位维护者或安全/SRE”要求继续适用。Owner 于 2026-08-29 已表达治理 bootstrap 决策意图，但每个治理/activation PR 仍须在候选存在后取得绑定 PR/base/head/tree/changed paths 的精确 owner attestation；取得前为 `PENDING`。

上述 exact attestation 经 API 逐字回读为 `VERIFIED`，并且同一候选的两路 fresh Agent review、trusted-control audit、required checks 和稳定窗口全部为 `VERIFIED` 后，只对该治理 PR 或 activation evidence PR 构成替代旧第二位人类前置的一次性 bootstrap authorization。Attestation 仍不是 verifier、GitHub `APPROVED` 或人类 review。PR #18 的 CI-B0 attestation 不可复用，该例外也不能被 PR #17、业务代码、保护设置或生产操作追溯使用。

DEC 不能授权自身。治理 PR 合并后仍保持 `PROPOSED / PENDING`；只有对已合并治理 commit 完成只读核验，并由不修改决策正文的独立 evidence PR 回填先前 merge SHA、再经普通受保护合并后，状态才可变为 `ACTIVE`。

## 1. 实施准入结论

前端、后端和运维控制面的模块化设计已经达到可实施状态：公开/管理/流式契约、租户模型、状态与计量、Provider 边界、容量方法、后台页面数据映射、M1 任务和测试证据均已冻结。实施必须从 MockProvider 的首条纵向切片开始，不能在真实云账号、容量卡和安全审阅尚未完成前宣称生产可用。

尚未关闭但不阻塞 M1 的外部验证：真实 Provider sandbox probe、目标环境压测、故障恢复演练、合规/留存评审、各端 SDK 互操作。这些是后续发布门，而不是允许跳过的待办。

## 2. 模块化交付路线

| 阶段 | 目标 | 主要后端模块 | 前端/运营模块 | 阶段退出条件 |
| --- | --- | --- | --- | --- |
| G0 仓库治理 | 建立可审阅、可追溯、可复现的工程入口 | Git、CI、依赖/secret/契约检查 | PR 模板、变更与风险记录 | main 保护策略和基础检查可运行；治理决策状态与证据可定位 |
| M1 可测核心 | MockProvider 下打通统一协议与 Relay 会话 | Core、Contract、State、Admission、Gateway、MockProvider、Observe | 无正式页面，仅 Admin API stub/测试工具 | M1-01 至 M1-11 及验收包全部关闭 |
| M2 首个真实数据面 | 接入一个已准入云 Provider 和受控 Relay | Provider Adapter、capability probe、熔断、连接治理 | Provider/路由最小管理接口 | sandbox probe、Adapter suite、单环境 canary 通过 |
| M3 Hybrid 与本地推理 | 建立 local-only 与 CPU Worker 路径 | Local Provider、Worker、VAD、缓存、资源隔离 | 本地模型/容量状态 API | RTF/质量/隔离测试、容量卡和故障演练通过 |
| M4 多租户运营后端 | 完整组织/空间/预算/质量/诊断管理面 | Admin API、RBAC、审批、用量/质量/诊断 | 前端所需聚合数据契约 | 管理资源清单与越权/审计测试全部通过 |
| M5 控制台实现 | 按已确认设计稿实现后台 | BFF/订阅接口补全 | 实时会话诊断、路由/版本/容量质量、空间成员三块页面 | 设计还原、权限/空态/异常态、接口契约测试通过 |
| M6 生产准备 | 完成可发布的多厂商高可用能力 | 第二 Provider、恢复、容量/发布自动化 | 告警、运行手册、发布操作面 | 实测容量卡、SLO、恢复/安全演练和灰度记录齐全 |

每一阶段只承接上阶段已验证的边界。前端 M5 虽已有确认设计稿，仍只能消费 M4 已脱敏、已授权、版本化的 API；不允许从日志、数据库或厂商控制台取数补洞。

## 3. 分支、提交与推送规则

```text
main (受保护，只接受 PR)
  <- feat/M1-07-session-control
  <- fix/M1-08-cancel-race
  <- docs/M1-fixture-clarification
  <- chore/ci-contract-validation
```

- 一个分支只对应一个工作包或一个可独立回滚的修复，分支名必须携带阶段/任务 ID。
- 不允许直接向 `main` 推送；任何变更先在任务分支完成检查、审阅、PR，再合并。
- 提交采用 `feat|fix|docs|test|refactor|chore(scope): summary`，正文必须说明关联任务、风险和验证命令/结果。
- 数据库 migration、公开契约、权限、限流、ticket、Provider、计量和删除逻辑的变更必须单独提交或与对应测试同提交，不与无关格式化混合。
- DEC-20260829-001 `ACTIVE` 后，`ZhangIvan` 可以提交并合并自己的 PR；owner 不计入独立 verifier quorum，且只能使用普通受保护合并。
- PR 必须记录语义风险等级、Finding 严重度、精确 base/head/tree、独立 Agent 报告、owner attestation、required checks、稳定窗口（如适用）和回滚路径。
- 合并后记录实际 merge commit、main workflow 结果与保护快照；未被路径规则调度的检查写 `NOT_SCHEDULED`，不得写成 `PASS`。Release tag 只能从已验证的 `main` 创建。

## 4. 每次变更的审阅机制

每次变更在 push 前依序执行：

1. 读取任务关联的设计文档、契约和 fixture，确认允许变化与冻结边界。
2. 按累计 diff 的**语义影响**判定 `CR0–CR4`；治理、CI、安全或生产语义不能因位于 `.md` 文件而降级。
3. 运行对应单元、集成、契约和安全检查；若无法运行，明确记录 `PENDING/INCONCLUSIVE`，不得省略或改写为通过。
4. 审阅正确性、状态机、取消/超时、资源释放、租户隔离、幂等、并发、错误映射、日志脱敏、指标基数、供应链和回滚影响。
5. 形成 PR：描述目的、范围、风险等级、Finding、测试证据、协议/数据迁移影响、容量/安全影响、回滚和未关闭项。
6. 取得与风险等级相符的独立 Agent review；Agent 是 verifier，不是 GitHub 人类 `APPROVED`。Owner attestation 不计入独立 reviewer quorum。
7. 核对 exact base/head/tree、实际 required checks、resolved conversations 和保护快照；`CR3` 还必须完成 trusted-control audit 与至少 10 分钟稳定窗口。
8. 只有所有不可豁免项关闭、合规 residual 已显式接受、讨论解决且 required checks 通过，才可普通受保护合并；合并后再记录 main 证据。

`CR` 是 Change Risk，与发布路线的 `R0–R8` 无关：`CR0` 为无规范语义的索引/排版/证据指针，`CR1` 为不改变接口、安全、依赖、CI 或运行行为的低风险变更，`CR2` 为普通行为/API 变化，`CR3` 为治理、CI/供应链、鉴权、租户、state/migration、admission、usage、Provider route、删除、公开契约、安全或生产配置语义，`CR4` 为真实外部/生产状态、凭据、客户数据、不可逆操作、部署、release/tag 或流量变更。完整门禁以 DEC-20260829-001 为准。

Finding 使用 `Finding-P0/P1/P2`：P0 永不例外；P1 默认阻塞，只能在精确范围、缓解、回滚、证据、有效期和失效条件齐全时由 owner 接受；P2 必须记录。P1 不能覆盖 secret、租户隔离、客户数据、不可恢复损坏、生产凭据/流量或外部人工门。

## 5. GitHub 保护策略

GitHub 仓库建立后，为 `main` 配置以下规则：

- Require pull request before merging，禁止 force push 和删除分支规则绕过。
- Require conversation resolution、线性历史和通过的 required status checks。
- 截至 2026-08-29 的 API 快照，required checks 为 `contract-fixtures`、`format-lint`、`unit`、`security`、`msrv`，均要求 GitHub Actions app 来源且 strict。每个候选仍必须从 GitHub API 读取当时实际配置和 check-run `head_sha`，不能把本行当作永久事实。
- 启用 secret scanning、push protection、Dependabot/security update；使用最小权限的 Actions token。
- `CODEOWNERS` 在创建 Organization/维护团队后启用：协议/安全/状态/Provider/前端目录分别指派对应团队，不能提交虚构 GitHub 用户名。
- 开启 release tag 保护；生产配置、密钥 reference、容量卡与 Provider 启用的变更要求审批记录。
- 当前 GitHub `required_approving_review_count=0` 不等于没有治理 review；DEC `ACTIVE` 后由独立 Agent verifier quorum 与 owner attestation 提供仓库证据。Agent 不能替代生产、人类责任或外部状态授权。

## 6. Pull Request 分类与强制关注点

| 变更类别 | 额外必须审阅 | 不可接受的情况 |
| --- | --- | --- |
| API/事件/SDK | OpenAPI/AsyncAPI diff、fixture、兼容性与弃用策略 | 改变 v1 必填/语义、透传厂商字段 |
| 鉴权/ticket/RBAC | scope、重放、日志、撤销、跨 Workspace | token 出现在 URL/日志；客户端可覆盖空间 |
| 会话/Relay/取消 | 状态机、bounded queue、race、资源 release | 无界缓存、已消费音频重放、双终态 |
| State/migration/outbox | 事务、幂等、TTL、恢复、数据删除 | 非原子预留、重复计量、不可恢复 migration |
| Provider/路由 | trait 边界、probe、熔断、费用与 fallback | 未准入厂商启用、Gateway 直接依赖 SDK |
| 计量/预算 | 单位、估算/对账、修正、审计 | 覆盖历史账务、缓存与云调用双计 |
| 前端 | 设计映射、权限、空/错误态、脱敏 | 直接读取日志/数据库、跨空间缓存 |
| CI/依赖 | 可复现、权限、供应链、运行成本 | 未锁定依赖、secret 注入日志、绕过 required check |
| 治理/保护 | 生效状态、supersedes、base/head/tree、verifier、attestation、稳定窗口、API 快照 | DEC 自授权、同名 check 假绿、admin/force/direct-main、把 Agent 写成人类审批 |

## 7. GitHub 建库与首次推送步骤

1. 初始化本地 Git 仓库并以当前设计资产建立首个基线提交。
2. 使用已登录的 GitHub CLI 或网页创建公开仓库 `QingYin`，不得把 Provider credential、真实录音、客户文本或环境 secrets 纳入仓库；公开前必须执行凭证模式扫描。
3. 添加 SSH 或 HTTPS `origin`，推送 `main`，核对云端 commit hash 与本地一致。
4. 在 GitHub 配置第 5 节分支保护和安全能力；创建维护团队后再提交正式 `CODEOWNERS`。
5. 从 `chore/G0-ci-governance` 开始通过 PR 建立第一个 CI/check 变更；通过后进入 `feat/M1-01-workspace-bootstrap`。

当前状态（2026-08-29 API 快照）：`ZhangIvan/QingYin` 已公开；`main@27320e74f8cb920add83d6094fb81233dbb29636` 已启用 PR、五项 required checks、strict、admin enforcement、讨论解决、线性历史，并禁止 force push 和删除；secret scanning、push protection 与 Dependabot security updates 已启用。此快照会过期，每个 PR 必须重新核验。DEC-20260829-001 尚未 `ACTIVE`，PR #17 不能追溯使用该提案。

## 8. 每阶段 Review 与反思记录

每个阶段完成后新增一份 `QingYin_<阶段>_验收与复盘.md`，至少记录：目标与范围、完成项、未完成项、测试/压测/探针证据、发现的问题、已修正项、风险、是否允许进入下一阶段，以及变更对应的 PR/commit。此记录是后续容量、Provider、前端和生产验收的输入，不允许以口头结论替代。

## 9. 生效、证据与回滚

- 单维护者规则以 DEC-20260829-001 的状态机为唯一来源；`PROPOSED/PENDING` 不具备常规授权能力。
- 治理 bootstrap 和 activation evidence PR 均按 `CR3` 执行；每个候选创建后分别取得并回读 exact owner attestation，未取得时保持 `PENDING`。验证后的 attestation 与同一候选两路 fresh review、trusted-control audit、required checks、稳定窗口共同构成该 PR 的一次性 bootstrap authorization，但不计入 verifier 或人类 approval。任一项或其证据变化都立即使 attestation/窗口失效。PR #18 证据不可复用，也不得传播给 PR #17 或其他变更。
- Evidence PR 只允许回填先前治理 merge SHA、已验证 evidence 和状态字段，不得修改决策正文，也不得使用自身未来 SHA 自证。
- 治理 docs-only merge 的 post-merge 证据按真实调度记录：`design-contracts` 写实际结果；Rust main-push 若因路径过滤未运行则写 `NOT_SCHEDULED`。
- DEC `ACTIVE` 后，PR #17 才能更新到新 `main` 并按 `CR3` 重新执行 trusted-control audit、两路 fresh review、五项 checks、owner attestation 和稳定窗口；旧证据全部失效。
- 规范回滚通过新的普通受保护 superseding/revert PR。Required context 或 workflow 破坏时优先 forward-fix；无法通过保护则 fail closed，并为任何保护迁移另行取得精确授权，禁止 admin/force 绕过。
