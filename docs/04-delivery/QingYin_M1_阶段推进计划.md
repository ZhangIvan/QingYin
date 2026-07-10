# QingYin M1：阶段推进计划

版本：v0.3
状态：M1-01/M1-02 收敛与后续执行基线
关联：M1 Rust 核心骨架、M1 契约 Fixture 与 MockProvider 规范、M1 实施 Backlog

## 1. 合并和依赖顺序

M1 使用“小 PR、强门禁、按依赖串行合并”。每个阶段从最新 `main` 创建独立分支，前一阶段完成 CI、Review 和合并后才开始下一阶段。

1. 保留并合并 M1-01 + M1-02，形成 workspace 与 canonical contract 基线。
2. M1-03 只实现 state trait、transaction、reservation、outbox 与 TTL fake。
3. M1-04 只实现 security context、principal、scope、ticket 与 redaction。
4. M1-05 只实现 admission gate、reservation lifecycle、retry-after 与幂等 release/settle。
5. M1-06 Provider Runtime 必须等待 M1-05 合并；M1-07 Gateway 必须等待 M1-02 至 M1-06 全部完成。

严禁把 M1-03、M1-04、M1-05 合入同一个 PR。阶段间的依赖通过已合并的 `main` 传递，不通过跨分支复制提交传递。

## 2. PR 边界

| 阶段 | 建议分支 | 允许的实现范围 | 明确不做 |
| --- | --- | --- | --- |
| M1-01 + M1-02 | `codex/-main`（PR #4） | workspace、工具链、CI、依赖门禁、fixture manifest、`qingyin-types` canonical 类型、`qingyin-contract` DTO/校验、最小 fixture testkit | state/security/admission/provider/gateway 运行行为 |
| M1-03 | `feat/m1-03-state-foundation` | 仅 `qingyin-state` 与 `qingyin-testkit`；Repository/transaction/reservation/outbox/TTL trait 和确定性内存 fake | Postgres/Redis、security、admission、Gateway handler |
| M1-04 | `feat/m1-04-security-context` | principal/scope、安全上下文、ticket hash/consume 边界、脱敏类型与测试 | 真实 KMS/密钥、Gateway middleware、admission gate |
| M1-05 | `feat/m1-05-admission-lifecycle` | `qingyin-admission` 准入闸门、reservation lifecycle、retry-after、release/settle 幂等及测试 | Provider fallback、真实容量探针、HTTP handler |

后续 PR 若必须修改表格之外的文件，只允许同步相关 Index、fixture/契约和 CI 门禁，并在 PR 描述中解释原因与兼容性影响。

## 3. 分阶段验收

| 阶段 | 必须证明的行为 | 自动化证据 |
| --- | --- | --- |
| M1-01 + M1-02 | crate 依赖方向固定；任务和模式分离；ID、状态、错误、事件、AudioSpec、SessionLease 与冻结契约一致 | `format-lint`、`unit`、`contract-fixtures`；OpenAPI/模块 01/12/20 对照 Review |
| M1-03 | 事务提交/回滚明确；reservation/outbox 原子边界可表达；TTL fake 使用虚拟时间且可重复；跨租户键不能碰撞 | 状态转换、事务、outbox 去重、过期/恢复、并发竞态单测 |
| M1-04 | principal 不能由请求体覆盖；scope 默认拒绝；ticket 只存 hash、绑定主体且只能消费一次；敏感值不进入 Debug/日志 | 越权、过期、撤销、并发消费、redaction 与 secret regression 单测 |
| M1-05 | 闸门顺序和拒绝原因稳定；拒绝包含可执行 retry-after；每个许可最多 settle 一次；release/settle 重试无副作用 | allowed/rejected/released/settled、重复调用、超时补偿和竞态单测 |

## 4. 每个 PR 的执行模板

1. 从最新 `main` 建分支，先运行基线检查并记录结果。
2. 在 PR 描述中列出目标、非目标、允许路径、依赖、fixture 和回滚方式。
3. 实现只解释约束、并发、安全和资源释放原因的维护性注释，不逐行复述代码。
4. 本地运行格式、lint、单测、契约、依赖边界、链接和 secret scan。
5. 先做一次作者自审，按严重级别记录并修正问题，再请求 GitHub Review。
6. required checks 全绿且讨论已解决后 squash merge；合并后删除分支并同步本地 `main`。

任何阶段发现前置契约缺陷时，先创建阻塞 Issue；不得借当前 PR 顺手扩展上一阶段或下一阶段的行为范围。
