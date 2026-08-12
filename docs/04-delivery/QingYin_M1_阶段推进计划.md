# QingYin M1：阶段推进计划

版本：v0.4
状态：M1-01 至 M1-04 已完成，M1-05 实现与门禁收敛中
关联：M1 Rust 核心骨架、M1 契约 Fixture 与 MockProvider 规范、M1 实施 Backlog

## 1. 合并和依赖顺序

M1 使用“小 PR、强门禁、按依赖串行合并”。每个阶段从最新 `main` 创建独立分支，前一阶段完成 CI、Review 和合并后才开始下一阶段。

1. M1-01 + M1-02 已通过 [PR #4](https://github.com/ZhangIvan/QingYin/pull/4) 合并，形成 workspace 与 canonical contract 基线。
2. M1-03 已通过 [PR #15](https://github.com/ZhangIvan/QingYin/pull/15) 合并 state trait、transaction、reservation、outbox 与 TTL fake。
3. M1-04 已通过 [PR #16](https://github.com/ZhangIvan/QingYin/pull/16) 合并 security context、principal、scope、ticket 与 redaction。
4. M1-05 [#7](https://github.com/ZhangIvan/QingYin/issues/7) 正在实现六门 admission、reservation lifecycle、retry-after、renew、幂等 release/settle 与过期回收。
5. M1-06 Provider Runtime 必须等待 M1-05 合并；M1-07 Gateway 必须等待 M1-02 至 M1-06 全部完成。

严禁把 M1-03、M1-04、M1-05 合入同一个 PR。阶段间的依赖通过已合并的 `main` 传递，不通过跨分支复制提交传递。

## 2. PR 边界

| 阶段 | Issue | 建议分支 | 允许的实现范围 | 明确不做 |
| --- | --- | --- | --- | --- |
| M1-01 + M1-02 | PR #4 | 已合并 | workspace、工具链、CI、依赖门禁、fixture manifest、`qingyin-types` canonical 类型、`qingyin-contract` DTO/校验、最小 fixture testkit | state/security/admission/provider/gateway 运行行为 |
| M1-03 | #5 | `feat/m1-03-state-foundation` | 仅 `qingyin-state` 与 `qingyin-testkit`；Repository/transaction/reservation/outbox/TTL trait 和确定性内存 fake | Postgres/Redis、security、admission、Gateway handler |
| M1-04 | #6 | `feat/m1-04-security-context` | 新增内层 `qingyin-security` 边界；principal/scope、安全上下文、ticket hash/consume、脱敏适配与测试 | 真实 KMS/密钥、Gateway middleware、admission gate |
| M1-05 | #7 | `feat/m1-05-admission-lifecycle` | `qingyin-admission` 准入闸门、reservation lifecycle、retry-after、release/settle 幂等及测试 | Provider fallback、真实容量探针、HTTP handler |

后续 PR 若必须修改表格之外的文件，只允许同步相关 Index、fixture/契约和 CI 门禁，并在 PR 描述中解释原因与兼容性影响。

## 3. 分阶段验收

| 阶段 | 必须证明的行为 | 自动化证据 |
| --- | --- | --- |
| M1-01 + M1-02 | crate 依赖方向固定；任务和模式分离；ID、状态、错误、事件、AudioSpec、SessionLease 与冻结契约一致 | `format-lint`、`unit`、`contract-fixtures`；OpenAPI/模块 01/12/20 对照 Review |
| M1-03 | 事务提交/回滚明确；reservation/outbox 原子边界可表达；TTL fake 使用虚拟时间且可重复；跨租户键不能碰撞 | 状态转换、事务、outbox 去重、过期/恢复、并发竞态单测 |
| M1-04 | principal 不能由请求体覆盖；scope 默认拒绝；ticket 只存 hash、绑定主体且只能消费一次；敏感值不进入 Debug/日志 | `security` 门禁；越权、过期、撤销、并发消费、redaction 与 secret regression 单测 |
| M1-05 | 六门顺序和拒绝原因稳定；拒绝包含合规 retry-after；租约可续且不复活终态；release/settle/回收只释放一次 | 全门 allowed/rejected、后续门回滚、重复/冲突终态、精确 TTL、续租、回收和竞态单测 |

## 4. M1 后半程 Issue 路线图

| 阶段 | Issue | 前置 | PR 关系 |
| --- | --- | --- | --- |
| M1-06 Provider Runtime | [#8](https://github.com/ZhangIvan/QingYin/issues/8) | #7 | 独立 PR，完成后启动 M1-07 |
| M1-07 Control Gateway | [#9](https://github.com/ZhangIvan/QingYin/issues/9) | #8 及 M1-02 至 M1-06 | 独立 PR，完成后解锁 M1-08/09/10 |
| M1-08 Relay Streams | [#10](https://github.com/ZhangIvan/QingYin/issues/10) | #9 | 独立 PR，可与 M1-09/10 并行 |
| M1-09 One-shot TTS HTTP | [#11](https://github.com/ZhangIvan/QingYin/issues/11) | #9 | 独立 PR，可与 M1-08/10 并行 |
| M1-10 Usage/observability | [#12](https://github.com/ZhangIvan/QingYin/issues/12) | #9、#5、#7 | 独立 PR，可与 M1-08/09 并行 |
| M1-11 Release evidence | [#13](https://github.com/ZhangIvan/QingYin/issues/13) | 全 M1 工作包 | 门禁持续建设，最终验收独立 PR |

M1 全部 Issue 归入 [M1 Core Foundation](https://github.com/ZhangIvan/QingYin/milestone/1) 里程碑。并行只表示可以从同一已验收基线创建不同 PR，不允许互相复制未合并提交或在一个 PR 中合并多个工作包。

## 5. 每个 PR 的执行模板

1. 从最新 `main` 建分支，先运行基线检查并记录结果。
2. 在 PR 描述中列出目标、非目标、允许路径、依赖、fixture 和回滚方式。
3. 实现只解释约束、并发、安全和资源释放原因的维护性注释，不逐行复述代码。
4. 本地运行格式、lint、单测、契约、依赖边界、链接和 secret scan。
5. 先做一次作者自审，按严重级别记录并修正问题，再请求 GitHub Review。
6. required checks 全绿且讨论已解决后 squash merge；合并后删除分支并同步本地 `main`。

任何阶段发现前置契约缺陷时，先创建阻塞 Issue；不得借当前 PR 顺手扩展上一阶段或下一阶段的行为范围。
