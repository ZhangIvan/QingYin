# QingYin 工程实施总计划与 GitHub 交付治理

版本：v0.2
状态：实施基线
关联：系统设计目录、设计冻结审阅、M1 核心骨架、M1 Backlog 与 CI 门禁

## 1. 实施准入结论

前端、后端和运维控制面的模块化设计已经达到可实施状态：公开/管理/流式契约、租户模型、状态与计量、Provider 边界、容量方法、后台页面数据映射、M1 任务和测试证据均已冻结。实施必须从 MockProvider 的首条纵向切片开始，不能在真实云账号、容量卡和安全审阅尚未完成前宣称生产可用。

尚未关闭但不阻塞 M1 的外部验证：真实 Provider sandbox probe、目标环境压测、故障恢复演练、合规/留存评审、各端 SDK 互操作。这些是后续发布门，而不是允许跳过的待办。

## 2. 模块化交付路线

| 阶段 | 目标 | 主要后端模块 | 前端/运营模块 | 阶段退出条件 |
| --- | --- | --- | --- | --- |
| G0 仓库治理 | 建立可审阅、可追溯、可复现的工程入口 | Git、CI、依赖/secret/契约检查 | PR 模板、变更与风险记录 | main 保护策略和基础检查可运行 |
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
- 合并后由 CI 在 `main` 重新执行检查；release tag 只能从已通过的 `main` 创建。

## 4. 每次代码推送前的审阅机制

每次代码变更在 push 前依序执行：

1. 读取任务关联的设计文档、契约和 fixture，确认不改变冻结边界。
2. 运行对应单元、集成、契约和安全检查；若无法运行，明确记录阻塞而不是省略。
3. 做一次变更审阅：检查正确性、状态机、取消/超时、资源释放、租户隔离、幂等、并发、错误映射、日志脱敏、指标基数和回滚影响。
4. 形成 PR：描述目的、风险、测试证据、协议/数据迁移影响、容量/安全影响与未关闭项。
5. CI 通过后进行独立 reviewer 审阅；只有所有讨论解决、必要审批完成、必需检查通过才合并。

自动化检查不能替代独立人工审阅。若早期只有单一维护者，PR 仍必须保留自检清单、自动检查和变更记录；涉及安全、计量、删除、公开 API 或生产路由的高风险变更必须增加第二位维护者或安全/SRE 审阅后才允许合并。

## 5. GitHub 保护策略

GitHub 仓库建立后，为 `main` 配置以下规则：

- Require pull request before merging，禁止 force push 和删除分支规则绕过。
- Require conversation resolution、线性历史和通过的 required status checks。
- 首批 required checks：`format-lint`、`contract-fixtures`、`unit`、`integration`、`security`、`review-gate`；后续增加 `sandbox-probe` 和 `load-smoke`。
- 启用 secret scanning、push protection、Dependabot/security update；使用最小权限的 Actions token。
- `CODEOWNERS` 在创建 Organization/维护团队后启用：协议/安全/状态/Provider/前端目录分别指派对应团队，不能提交虚构 GitHub 用户名。
- 开启 release tag 保护；生产配置、密钥 reference、容量卡与 Provider 启用的变更要求审批记录。

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

## 7. GitHub 建库与首次推送步骤

1. 初始化本地 Git 仓库并以当前设计资产建立首个基线提交。
2. 使用已登录的 GitHub CLI 或网页创建私有仓库 `QingYin`，不得把 Provider credential、真实录音、客户文本或环境 secrets 纳入仓库。
3. 添加 SSH 或 HTTPS `origin`，推送 `main`，核对云端 commit hash 与本地一致。
4. 在 GitHub 配置第 5 节分支保护和安全能力；创建维护团队后再提交正式 `CODEOWNERS`。
5. 从 `chore/G0-ci-governance` 开始通过 PR 建立第一个 CI/check 变更；通过后进入 `feat/M1-01-workspace-bootstrap`。

当前已知环境限制：本机 GitHub CLI 未登录，且当前目录的 `.git` 是空目录。可以安全建立本地仓库基线，但创建远端/推送需要用户完成 GitHub 登录或提供已存在的私有仓库地址。

## 8. 每阶段 Review 与反思记录

每个阶段完成后新增一份 `QingYin_<阶段>_验收与复盘.md`，至少记录：目标与范围、完成项、未完成项、测试/压测/探针证据、发现的问题、已修正项、风险、是否允许进入下一阶段，以及变更对应的 PR/commit。此记录是后续容量、Provider、前端和生产验收的输入，不允许以口头结论替代。
