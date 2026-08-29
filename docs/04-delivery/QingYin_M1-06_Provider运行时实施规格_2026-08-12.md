# QingYin M1-06：Provider 运行时实施规格

版本：v0.1
日期：2026-08-12
状态：READINESS；实现入口被 G0 硬门阻断
关联：M1-06 / Issue #8、M1 Rust 核心骨架、M1 契约 Fixture 与 MockProvider 规范、M1 实施 Backlog、G0 / M1-05 验收与复盘

## 1. 文档定位与启动硬门

本文把 M1-06 的 Provider Runtime、不可变 registry、Scripted MockProvider 和 Provider Contract Suite 冻结为可直接执行的实施规格。它只形成下游 readiness，不代表 M1-06 已启动、已实现、已验收或已合并，也不改变当前 G0、M1-05、G1 或生产发布状态。

M1-06 只有同时满足以下条件后才能开始实现：

1. G0 / M1-05 验收状态明确更新为 ACCEPTED。
2. M1-05 候选已通过固定 Rust 1.97 required checks、独立 Review 和 discussion resolution。
3. M1-05 已合并到 main，且可定位合并 commit。
4. M1-06 从该已验收 main commit 创建独立分支，不复制未合并提交。
5. 开工记录包含 base SHA、Issue、允许路径、禁止范围、验证命令和回滚方式。

任一条件不满足时，只允许继续审阅、风险关闭和测试设计，不得修改 Provider、MockProvider、Gateway 或共享契约的运行行为。

## 2. 当前事实基线

截至本文日期：

- qingyin-provider 只有 crate 边界注释和 qingyin-types、qingyin-contract 依赖，没有 trait、capability、registry、error 或 runtime 实现。
- qingyin-mock-provider 只有边界注释和 qingyin-types、qingyin-provider 依赖，没有 profile、虚拟时序、调用记录或 ASR/TTS 实现。
- qingyin-gateway 只有组合边界注释，没有 HTTP、WebSocket、handler 或会话编排；其运行行为属于 M1-07 及以后。
- contracts/fixtures/v1/manifest.json 已冻结 7 个 MockProvider profile 名称，但尚未形成 contracts/mock-profiles/ 实体脚本。
- qingyin-types 已提供 TaskKind、SessionMode、AudioSpec、canonical error code、event type 和通用 EventEnvelope。
- Rust contract 层尚未实现完整 CreateSessionRequest、流式控制帧和各事件 payload；M1-06 不得借机扩展或破坏公开 v1 契约。
- qingyin-testkit::VirtualClock 服务于 State/TTL，只有同步 now/advance，不具备 pending future 唤醒语义；MockProvider 应使用独立、可唤醒的虚拟 timeline。

## 3. 目标与非目标

### 3.1 M1-06 必须交付

- runtime-neutral、object-safe 的 ASR/TTS Provider trait 和 session trait。
- 严格校验、可审计且对 session 不可变的 capability/provider snapshot。
- build/freeze 型 Provider registry、控制面 catalog 和类型化 execution handle。
- canonical、阶段化、脱敏的 Provider error 与 retry/replay 语义。
- Provider 内部有界、需求驱动的 input/output 契约；达到上限时暴露 backpressure，不允许无界缓冲。
- 明确的 cancel/timeout 终止路径；所有 pending I/O、task、channel、permit 和 handle 必须确定性收敛。
- 单调累计的 Provider usage snapshot，不承担 exactly-once 账务。
- 7 个闭集 MockProvider profile、无真实网络的虚拟时序和有界调用记录。
- 可被未来真实 Adapter 复用的 Provider Contract Suite。
- profile manifest、实体 profile 和 Rust enum 的一一对应门禁。

### 3.2 M1-06 明确不做

- Gateway HTTP/WS handler、认证 middleware、session create/get/cancel。
- Gateway/Relay 的公共传输 channel、慢消费者策略、durable timeout 终态和一秒取消 SLO 证明；Provider 自身的有界 I/O、timeout/cancel 收敛仍属于 M1-06。
- One-shot TTS HTTP 首字节语义。
- 路由评分、跨 Provider fallback、熔断、健康权重或生产容量结论。
- Admission reservation、release/settle/reclaim 或 ProviderPoolId 选择。
- usage/outbox exactly-once consumer、账务、生产指标导出。
- 真实 Provider SDK、HTTP 客户端、DNS、凭证、网络或 sandbox probe。
- Direct SDK、Local Worker、Realtime/LLM 运行路径。
- OpenAPI/AsyncAPI breaking change 或真实 PostgreSQL/Redis。

## 4. 职责与依赖边界

| 领域 | qingyin-provider | qingyin-mock-provider | Gateway / 后续阶段 |
| --- | --- | --- | --- |
| 租户、认证、权限 | 不依赖、不接收 | 不感知 | M1-07 使用 SecurityContext |
| 路由与准入 | 提供不可变能力和执行 handle | 提供固定 mock 能力 | M1-07 服务端路由并构造 Admission 输入 |
| Provider 容量池 | 不依赖 qingyin-admission | 不指定 | 可信 route/config 映射 ProviderId -> ProviderPoolId |
| 事件 | 只输出规范化 payload | 只产生规范化 payload/抽象错误 | M1-08/09 生成 envelope、sequence 和传输帧 |
| 错误 | 分类、阶段、重放安全和脱敏映射 | 注入闭集抽象错误 | Gateway 映射 HTTP/WS 与 durable terminal |
| 文本/音频 | 有界、需求驱动 I/O，Debug 脱敏 | 固定 I/O 上限；仅 synthetic；调用记录不存原文 | Gateway 验证、传输背压和公共协议 |
| usage | 单调累计 Provider 使用量 | 确定性计数 | M1-10 转换并 exactly-once settle |
| profile | 核心 crate 不感知 | 闭集 7 profile | 仅 dev/test 配置，不可来自外部请求 |
| runtime/network | 不依赖 Tokio、Axum、Reqwest 或厂商 SDK | 无真实网络、无 wall-clock sleep | M1-07/08/09 持有具体 runtime |

以下依赖方向必须保持：

    qingyin-gateway -> qingyin-provider
    qingyin-mock-provider -> qingyin-provider
    qingyin-testkit -> qingyin-provider

qingyin-provider 不得依赖 Gateway、Admission、State、Security、Observe、MockProvider 或 testkit。qingyin-mock-provider 不得成为 Gateway 的普通依赖；后续只能作为 dev-dependency 使用。

## 5. 开工前冻结的设计决定

### D1：TTS 统一为会话模型

现有架构草图中的 TtsProvider::synthesize 无法完整承载后续 WS text_append、text_commit、text_replace 与 one-shot HTTP。M1-06 统一采用会话模型：

    TtsProvider::create_session
    TtsSession::input_ready
    TtsSession::send(TtsInput)
    TtsSession::next_event
    TtsSession::finish
    TtsSession::cancel
    TtsSession::timeout
    TtsSession::usage

TtsInput 是 Append | Commit | Replace 的闭集；one-shot 由一个 session 和一个完整 commit 表达，不再建立第二套 Adapter 生命周期。相同 commit ID 与相同内容重试幂等；相同 ID 与不同内容冲突；已经开始输出的 segment 禁止替换。

ASR session 至少提供 input_ready、send_audio、flush、next_event、finish、cancel、timeout 和 usage。flush 只表示 utterance 边界，不终止整个输入流。

ProviderCapabilitySnapshot 必须声明非零且有上限的 ProviderIoLimits，包括 in-flight input items/bytes 和 buffered output items/bytes。input_ready 与 send 形成一个有界许可协议：上限用尽时调用者只能等待 readiness 或收到受控 backpressure，不能把数据追加到无界 Vec/channel。next_event 是需求驱动的 pull 边界；Adapter 若必须接收推送，只能在声明的 output 上限内缓冲，超限时 fail closed 并终止 session。

timeout 是 Provider session 的显式终止操作，由外层 supervisor 在可信、受限的 deadline 到达时调用，或由 Adapter 在上游 timeout 时触发。它必须唤醒所有 pending input/output、终止底层工作并稳定产生 provider_timeout；重复 timeout 以及 timeout 后的 cancel 均不得再次调用底层或重复累计 usage。Gateway 如何持久化 timeout、释放 Admission 和关闭公共传输留给后续阶段。

### D2：Provider 只输出 payload，Gateway 拥有 envelope

Provider 不得创建完整 EventEnvelope。推荐闭集：

- AsrOutput：VadStarted、VadEnded、Partial、Final、FinalUpdate。
- TtsOutput：AudioStarted、AudioChunk、Mark、AudioEnded。

Provider output 不包含可由 Adapter 任意设置的 QingYin session_id、trace_id、event_id、全局 event sequence 或 service timestamp。Gateway/Relay 在 M1-08/09 用可信 session context 包装 envelope。

TTS AudioChunk 必须把 audio identity、audio sequence、segment identity、byte length 与 bytes 绑定为一个强类型结果，后续 Gateway 再产生相邻 metadata event 和 binary frame，避免 metadata/bytes 错配。

### D3：Registry build/freeze 与 snapshot pinning

Registry 采用不可变快照，而不是可变全局映射：

    ProviderRegistryBuilder
      -> 校验注册、重复 ID、task、snapshot 与 handle 一致性
      -> freeze
    ProviderRegistrySnapshot
      -> control catalog
      -> typed execution handles

一个 session 必须固定：

- 精确 ProviderId。
- 精确 ProviderSnapshotId。
- 与该 snapshot 绑定的 Arc execution handle。

配置 reload 创建新的 frozen registry，不能原地修改旧 snapshot。活跃 session 继续持有旧 handle 直到 drain；已有 session 禁止通过 latest 再解析 Provider。控制面 catalog 与 execution handle 必须是不同类型，catalog 不暴露 mock profile、凭证、原生 endpoint 或可调用对象。

### D4：错误映射区分阶段和重放安全性

Provider error 至少包含：

- ProviderErrorKind。
- ProviderErrorStage：Create、Input、Output、Finish、Cancel、Timeout。
- ReplaySafety：SafeBeforeInput、UnsafeAfterInput、Unknown。
- 有界 retry_after_ms。
- 可选、受控的 DiagnosticId。

错误对象不得保存或格式化上游原始 message、URL、header、响应体、凭证、全文文本或音频。

| Provider 分类 | 默认 canonical 映射 | 额外规则 |
| --- | --- | --- |
| quota/rate | quota_exhausted 或 rate_limited | 只传播有界 retry-after |
| unsupported | unsupported_capability | create 前拒绝，不创建 session |
| invalid audio/input | invalid_audio / invalid_request | 不可重试 |
| timeout | provider_timeout | create 前可安全重试；消费输入后默认不可重放 |
| unavailable | provider_unavailable | 由阶段覆盖 retryable，流中不得静默重放 |
| protocol | provider_protocol_error | 非法原生消息不能穿透强类型边界 |
| internal | internal_error | 只返回受控诊断 ID |

Provider 上游凭证失败不能映射为面向客户的 auth_invalid，因为该 code 已表示 QingYin credential 无效。对外使用非重试的 provider_unavailable，内部保留 Provider authentication 诊断分类。

### D5：MockProvider 使用专属可唤醒虚拟 timeline

MockProvider 自有 MockTimeline 和 MockControl::advance：

- 事件未到期时 next_event 真正保持 Pending。
- advance、I/O capacity release、cancel、timeout 或 terminal transition 唤醒对应 waker。
- 唤醒动作在释放内部锁后执行。
- 时间只允许单调前进，溢出和亚毫秒不精确输入 fail closed。
- 不使用 wall-clock sleep、Tokio timer、网络或 runtime-global state。

脚本步骤、in-flight input、待输出队列、调用记录和并行 session 数都必须有显式 item/byte 上限。input 或 output 达到上限时必须呈现可测试的 backpressure；协议违规或无法继续消费时返回受控错误并清理，不允许测试工具形成无界内存增长。

## 6. 推荐模块与类型表面

推荐把 qingyin-provider 拆分为：

    src/
      capability.rs
      error.rs
      model.rs
      registry.rs
      traits.rs
      lib.rs

核心类型建议包括：

- ProviderId、ProviderSnapshotId：Provider 内部强类型 ID，不使用裸字符串作为 map key。
- ProviderIoLimits：非零且有界的 input/output item/byte 上限，属于 capability snapshot 的不可变部分。
- ProviderCapabilitySnapshot：task、mode、transport、语言、features、输入/输出 AudioSpec、限制和 snapshot identity。
- AsrCreateRequest、TtsCreateRequest：只承载执行必需的规范化参数，不含 tenant、policy、credential、Provider hint 或 Admission 对象。
- AudioFrame、TtsInput：构造时校验基本边界，Debug 不展示 bytes/text。
- AsrOutput、TtsOutput：不含完整 QingYin envelope identity。
- ProviderUsageSnapshot：累计输入/输出字节和 Provider units，使用 checked arithmetic，终态后保持稳定。
- AsrProvider、AsrSession、TtsProvider、TtsSession：Send、必要处 Sync、可装入 trait object，且不绑定具体 async runtime。
- ProviderRegistryBuilder、ProviderRegistrySnapshot、AsrExecutionHandle、TtsExecutionHandle。

转写文本、TTS 文本和音频 bytes 可以通过受控 accessor 进入真实数据路径，但其 Debug/Display 必须固定脱敏。不得把 CanonicalError::message 当作上游原始错误的容器。

## 7. 状态机

### 7.1 Registry 生命周期

    Building -> Frozen
    Frozen --reload--> New Frozen
    Old Frozen --active Arc--> retained until drain

- Frozen 后没有注册、删除或原地 mutation API。
- 重复 Provider ID、重复 snapshot ID、task/handle 不匹配、非法 capability 均使 freeze 失败。
- catalog 枚举顺序必须确定，不能依赖 HashMap 随机顺序。

### 7.2 ASR session

    Open -> InputClosed -> Completed
    Open/InputClosed -> Cancelled | TimedOut | Failed

| 操作 | Open | InputClosed | Terminal |
| --- | --- | --- | --- |
| send_audio | 允许，sequence 严格连续 | 拒绝 | 拒绝/稳定终态 |
| flush | 允许，可形成 utterance 边界 | 拒绝 | 拒绝/稳定终态 |
| finish | 首次关闭输入 | 幂等 no-op | no-op |
| next_event | 允许 | 允许 drain | 稳定 None |
| cancel | 调用底层一次并取消 | 调用底层一次并取消 | 幂等 no-op |
| timeout | 终止底层并返回 provider_timeout | 同左 | 幂等返回相同终态 |

Open 状态出现上游 EOF 视为失败，不能伪装正常完成。Provider output 出错后 session 进入 Failed；已消费音频默认不可重放。input_ready/send_audio 必须遵守 ProviderIoLimits，并在 capacity 释放、cancel 或 timeout 时唤醒。Drop 必须使 Mock session 资源和 active count 收敛，不能假设所有调用者都能成功 await cancel。

### 7.3 TTS session 与 commit

Session 主状态：

    Open -> InputClosed -> Completed
    Open/InputClosed -> Cancelled | TimedOut | Failed

每个 commit 的局部状态：

    Buffered -> Committed -> Started -> Ended
    Committed -> Replaced

- 只有 committed text 可以产生 mark 或 audio。
- replace 只允许作用于未 Started 的 commit。
- cancel 后不得再产生 chunk、mark 或第二个 terminal。
- timeout 后不得再产生 chunk、mark 或第二个 terminal；所有 pending readiness/output 必须被唤醒。
- finish/cancel/timeout 重试不重复 usage、Provider 调用或输出。

### 7.4 Mock profile/session

    Configured -> Created -> Running -> Completed | Cancelled | Failed
    Configured -> CreateRejected

Profile 和脚本在 Provider 构造时冻结，session request 不能选择或覆盖。每个 session 获得独立脚本游标和 usage；共享 timeline/control 不得造成跨 session 事件串流。

## 8. 七个 MockProvider Profile

| Profile | ASR 行为 | TTS 行为 | 必须断言 |
| --- | --- | --- | --- |
| happy | frame 后按脚本产生 VAD/partial/final | commit 后产生 started/chunk/ended | 严格顺序、usage、资源回收 |
| slow_first | 延迟首 partial | 延迟首音频 | advance 前 Pending，advance 后唤醒，无 sleep |
| create_reject | create 立即失败 | create 立即失败 | 不产生 ready/session，active 为零 |
| fail_midstream | partial 后失败 | 至少一个 chunk 后失败 | 不重放、不出现第二终态 |
| hang_until_cancel | 一直 Pending 到 cancel/timeout | 一直 Pending 到 cancel/timeout | 两条终止路径均唤醒、无后续输出、资源归零 |
| quota_exhausted | 返回上游配额错误 | 返回上游配额错误 | code、retry-after、未创建 session |
| protocol_violation | Adapter 检测并返回 protocol error | Adapter 检测并返回 protocol error | 非法消息不穿透 typed output |

Profile 文件必须满足：

- schema_version=v1、privacy_class=synthetic。
- 名称与 manifest、Rust enum 完全一致且无额外项。
- 只使用 canonical output 和抽象 error，不模拟厂商 wire protocol。
- 文本、音频、ID 和时间均为固定 synthetic 数据。
- 延迟、步骤数、文本长度和 bytes 有显式上限。
- 不包含 URL、credential、token、真实 Provider 名或用户数据。

## 9. Provider Contract Suite

通用套件放在 qingyin-testkit，普通依赖 qingyin-provider。qingyin-mock-provider 通过 dev-dependency 调用套件；testkit 不依赖 MockProvider，从而避免依赖环。未来真实 Adapter 也通过 dev-dependency 复用同一套件。

最低覆盖：

1. trait object 的 object safety、Send/Sync 边界和无 runtime 绑定。
2. capability 与 create request 协商一致；unsupported 在 create 前失败。
3. capability collection 的非空、上限、去重、确定性顺序与 AudioSpec 校验。
4. registry 重复 ID、错误 task、错误 snapshot、确定性 lookup 和 catalog/handle 分离。
5. registry A -> B reload 后，A 中已创建 session 仍引用 A。
6. ASR frame sequence、flush、finish/cancel/timeout 幂等、EOF 和错误终态。
7. ASR partial stable prefix、utterance identity 和 final 顺序。
8. TTS append/commit/replace、commit conflict、chunk sequence 和已播放段不可替换。
9. 每个 error kind × stage 的 canonical code、retryable、retry-after 和 replay safety。
10. create、input、output 和 finish 阶段的 ProviderTimeout 都终止底层工作、返回 provider_timeout，且已消费输入后不允许静默重放。
11. usage 单调、checked arithmetic、终态稳定和重复操作不重复累计。
12. input item/byte 上限耗尽时后续 input 呈现 backpressure；capacity 释放后只唤醒有许可的 waiter，不复制或丢失已接受输入。
13. output item/byte 缓冲不超过上限；未调用 next_event 时 producer 不得无界推进或增长。
14. cancel、timeout 或 drop 后 active session、pending I/O/waker、channel、permit、脚本队列和调用记录全部收敛。
15. 多 session 隔离；一个 session 的 profile cursor、usage、backpressure 或 terminal 不影响另一个。
16. Debug/Display、error、调用记录不含 synthetic 原文、audio bytes、token 或原始上游错误。
17. 有界脚本、调用记录和 session 上限达到时 fail closed。
18. manifest、7 个 profile 文件与 Rust profile enum 精确一致。

Contract Suite 分为两层：

- 黑盒 Provider 契约：只依赖 Provider trait，可由未来真实 Adapter 运行。
- Mock profile 扩展：使用 MockControl 驱动虚拟时间、错误注入和资源计数。

完整 provider.timeout.v1 的 Gateway durable 终态、reservation release、circuit metric 和公共传输关闭属于 M1-08/09/10；M1-06 必须证明 Provider 层的虚拟延迟、bounded I/O backpressure、timeout/cancel 终止收敛和阶段化错误映射。

## 10. 实施分解

M1-06 保持一个 Issue、一个独立 PR。PR 内按以下顺序实施：

1. **基线与决定记录**：绑定已验收 main SHA；在 PR 描述确认 D1-D5、目标、非目标、允许路径和回滚。
2. **Provider 模型层**：实现 ID、capability snapshot、request/input/output、usage、敏感包装和 error mapping，并先完成纯单测。
3. **Traits 与生命周期**：实现 runtime-neutral ASR/TTS trait、ProviderIoLimits、需求驱动 I/O、session terminal 规则和幂等 finish/cancel/timeout。
4. **Registry**：实现 builder/freeze、control catalog、typed execution handle、snapshot pinning 和 reload 回归。
5. **Contract Suite**：新增 testkit Provider 套件，覆盖 bounded I/O、timeout/cancel 收敛并更新依赖边界 validator；testkit 不依赖 MockProvider。
6. **MockProvider**：实现 ASR/TTS、闭集 profile、虚拟 timeline、调用记录和资源统计；所有 profile 运行同一套件。
7. **Profile assets**：创建 7 个严格、versioned、synthetic profile，扩展 fixture validator。
8. **文档与门禁**：补 Provider/MockProvider README、状态记录和验证证据；不修改 Gateway 行为。

建议允许修改路径：

- crates/qingyin-provider/**
- crates/qingyin-mock-provider/**
- crates/qingyin-testkit/Cargo.toml
- crates/qingyin-testkit/src/provider.rs
- crates/qingyin-testkit/src/lib.rs
- 必要的 crates/qingyin-testkit/README.md
- contracts/mock-profiles/**
- contracts/fixtures/v1/manifest.json，仅在保持既有 ID 语义时更新引用
- scripts/validate_contract_fixtures.py
- scripts/validate_workspace_boundaries.py
- 必要的 Cargo.lock、Makefile、CI 和 M1 delivery 状态文档

禁止修改范围：

- crates/qingyin-gateway/src/** 的运行行为。
- Admission、State、Security、Observe 的既有语义。
- OpenAPI/AsyncAPI 的 v1 breaking 字段或事件。
- 真实 Provider、网络、生产配置、部署和 secret。
- M1-07/08/09/10 的 handler、stream、settlement 或观测行为。

若发现必须修改禁止范围，停止当前 PR，创建阻塞 Issue 并重新完成范围与兼容性 Review；不得以顺手修复方式扩大 M1-06。

## 11. 风险与停止条件

### P0 / 立即停止

- G0 未 ACCEPTED 即开始代码实现。
- 从 dirty tree、M1-05 未合并分支或未验收 commit 创建 M1-06。
- MockProvider 或真实 Provider 行为混入 M1-05 PR。
- 发现跨租户、credential、音频/文本或 Provider secret 泄漏。

### P1 / 合并前必须关闭

- TTS one-shot 与增量 session 仍有两套冲突生命周期。
- reload 后已有 session 使用 latest Provider/profile，而非原 snapshot。
- Provider 可伪造完整 event envelope identity。
- 上游 Provider auth 错误误映射为 QingYin auth_invalid。
- cancel/timeout/drop 无法唤醒 pending I/O，或残留 task、channel、permit、handle、active-count。
- input/output 缺少 item/byte 上限，或上限耗尽时通过隐藏队列继续接受数据而不呈现 backpressure。
- Provider 直接依赖 Admission/Security/State 或自行选择 ProviderPoolId。
- Mock profile 可被外部 request、metadata 或 header 选择。
- MockProvider 进入 Gateway 普通依赖或 release artifact dependency closure。
- raw text、audio、上游 error、URL、header 或 token 进入 Debug、调用记录或 canonical message。
- script、I/O 队列、调用记录或 session 数无界。

### P2 / 显式记录并留给后续阶段

- Rust contract DTO/event payload 尚不完整；M1-06 使用 Provider 内部类型，不顺手扩展公共 API。
- Gateway 尚未直接依赖 Security；由 M1-07 明确补齐。
- State 仅保存通用 provider snapshot 引用；M1-07 route snapshot 必须同时持久化精确 Provider 选择。
- 熔断、Gateway durable timeout 编排与 SLO、低基数 metric 和 exactly-once usage settlement 分别留给 M1-08/09/10 或生产 Provider 阶段；Provider-level timeout 契约不后移。

## 12. 验收门与完成证据

M1-06 可申请 Review 前，至少运行并保存：

    cargo fmt --all --check
    cargo check --workspace --all-targets --all-features --locked
    cargo clippy --workspace --all-targets --all-features --locked -- -D warnings
    cargo test -p qingyin-provider -p qingyin-mock-provider -p qingyin-testkit --all-targets --all-features --locked
    cargo test --workspace --all-targets --all-features --locked
    cargo test --workspace --doc --all-features --locked
    RUSTDOCFLAGS="-D warnings" cargo doc --workspace --all-features --no-deps --locked
    python3 scripts/validate_workspace_boundaries.py
    python3 scripts/validate_contract_fixtures.py
    python3 scripts/validate_secret_regressions.py
    python3 scripts/validate_design_assets.py
    python3 scripts/validate_markdown_links.py

本地 make check 应覆盖上述 workspace 门禁；远端 required checks 同时包含固定 Rust 1.97 全量门与 Rust 1.85 MSRV 编译门。最终证据必须绑定同一 commit，并包括：

- base/main SHA、候选 commit 和 Cargo.lock。
- Provider/MockProvider/testkit 依赖图。
- Provider Contract Suite 与 7 profile 逐项结果。
- registry snapshot pinning、bounded I/O backpressure、timeout/cancel/drop 收敛、usage 幂等和 privacy 测试结果。
- fixture manifest/profile hash。
- workspace、fixture、secret、docs、rustdoc 门禁结果。
- 独立 reviewer 对 registry、错误重放、取消和敏感数据边界的结论。
- required checks 全绿和 discussion resolved 证据。

以下事实不得被验收报告混淆：本地通过不等于 CI 通过；CI 通过不等于 Review 完成；M1-06 合并不等于 G1 完成；MockProvider Contract Suite 不证明真实 Provider、真实容量、生产 SLO 或可发布性。

只有 M1-06 独立 PR 合并到 main 后，M1-07 才可从新的已验收 main 基线开始 Gateway 实现。
