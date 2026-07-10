# QingYin M1：后续阶段推进计划

版本：v0.2
状态：M1-01 后执行计划
关联：M1 Rust 核心骨架、M1 契约 Fixture 与 MockProvider 规范、M1 实施 Backlog

## 1. 推进原则

M1 后续任务继续保持“小 PR、强门禁、按依赖串行合并”的节奏。每个任务只在前一任务完成 CI 与审阅后开始落地下一项，避免在同一 PR 中同时改变公开契约、状态持久化和运行时行为。

每个任务开始前必须重新确认：

1. `docs/INDEX.md`、`docs/04-delivery/` 与相关架构模块是否有新变更。
2. 当前分支是否已从最新 `main` 或本地可用基线同步。
3. `contract-fixtures`、`format-lint`、`unit` 是否能在任务开始和结束时复现。
4. 任务是否有明确的 fixture ID、公开契约影响、错误/隐私影响与 DoD。

## 2. M1-02 至 M1-05 方案

| 阶段 | 目标 | 主要落地内容 | 不做事项 | 完成证据 |
| --- | --- | --- | --- | --- |
| M1-02 | Canonical types/contract | ID、时间、任务、状态、错误、事件信封、AudioSpec、SessionLease 与 fixture envelope 的可校验类型；最小 contract 单测 | 不接 HTTP server，不写 Provider runtime，不落库 | 类型单测、fixture manifest 校验、公开 DTO 与模块 12/20 对齐 |
| M1-03 | Durable/Ephemeral State | Repository trait、事务接口、reservation/outbox 抽象、TTL store trait、内存 test double | 不接 Postgres/Redis 真实实例，不引入 Gateway handler | 状态机、幂等、TTL、outbox 去重单测 |
| M1-04 | Security context | credential/principal/scope/ticket 抽象、ticket hash/consume trait、日志脱敏策略 | 不实现真实密钥管理，不开放公网认证 | ticket 单次消费、过期、主体绑定、redaction 单测 |
| M1-05 | Admission | capacity/policy/budget gate、reservation lifecycle、retry-after、release/settle 幂等 | 不做真实容量卡探针，不做跨 Provider fallback | allowed/rejected/released、竞态幂等与指标维度单测 |

## 3. 依次推进顺序

1. **先合并 M1-01**：只保留 workspace、门禁入口、fixture manifest 和依赖边界校验。
2. **M1-02**：在 `qingyin-types` 与 `qingyin-contract` 内补齐 canonical 类型和 DTO，并将 `contract-fixtures` 作为契约入口继续收紧。
3. **M1-03**：只触碰 `qingyin-state` 和 `qingyin-testkit` 的状态 fake，避免与 Provider/Gateway 并发开发冲突。
4. **M1-04**：只触碰安全上下文、ticket 与 redaction，不改变 admission 或 runtime。
5. **M1-05**：在 M1-03/04 之后实现 admission gate 和 reservation 释放语义。

`M1-06` Provider Runtime 必须等 M1-02 的 canonical event/error 和 M1-05 的 admission/release 边界稳定后再开始；`M1-07` Gateway 必须等 M1-02 至 M1-06 均完成后再开放 handler。
