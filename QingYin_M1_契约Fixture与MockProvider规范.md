# QingYin M1：契约 Fixture 与 MockProvider 规范

版本：v0.2
状态：实现准备基线，尚未创建测试代码或 fixture 文件
关联：模块 01、02、12、13、15、16、17；三份 API 契约

## 1. 目标

Fixture 是 QingYin v1 的可执行语义来源，而不是演示样例。Gateway、SDK、MockProvider、真实 Provider Adapter 和管理面都必须从同一套 fixture 验证事件顺序、错误、状态、计量和隔离规则。任何新增 Adapter 不得以厂商“实际行为不同”为由绕过 canonical 语义。

M1 先定义 fixture 格式、目录和覆盖矩阵；实现阶段再创建与文档一一对应的 JSON/binary fixture。测试材料只能使用合成音频、合成文本和虚拟凭证，禁止录入真实用户音频、真实 Provider URL 或有效密钥。

## 2. 计划目录与 fixture 信封

后续实现采用如下目录，所有路径在契约仓库内版本化：

```text
contracts/
  fixtures/v1/
    manifest.json
    control/
    streaming/asr/
    streaming/tts/
    streaming/realtime/
    errors/
    tenancy/
    state/
    provider/
    compatibility/
  mock-profiles/
```

每一个 fixture 必须声明下列元数据，fixture 名称不得依赖具体厂商：

| 字段 | 规则 |
| --- | --- |
| `fixture_id` | 稳定、唯一，如 `asr.ws.happy.v1`；重命名视为兼容变更 |
| `schema_version` | 固定为 `v1`；主版本变更创建新目录 |
| `category` | `control`、`streaming`、`error`、`tenancy`、`state`、`provider` 或 `compatibility` |
| `seed` | 固定时间、ID、虚拟主体、配置 snapshot、能力 snapshot；禁止真实凭证 |
| `input` | HTTP request、WS text/binary frame、状态前置条件；binary 只用生成字节和摘要 |
| `expected` | HTTP response、canonical event 序列、close/terminal state、持久化/计量摘要、metric 增量 |
| `assertions` | 严格顺序、允许集合、禁止字段、超时上限、幂等性和隐私断言 |
| `privacy_class` | 固定为 synthetic；若未来需要受控测试集，单独审批和目录隔离 |

所有时间使用虚拟单调时钟，所有 ID 使用固定测试值；集成测试可以校验 ID 前缀和关联关系，但不得依赖随机完整值。

## 3. 必须实现的黄金路径

| Fixture ID | 输入 | 预期规范结果 | 额外断言 |
| --- | --- | --- | --- |
| `control.session.create.asr.v1` | 有效 ASR request、project credential、幂等 key | `201 SessionLease`，有效 ASR ticket，`leased` session | route/reservation/audit/outbox 同事务出现；无 Provider 凭证 |
| `asr.ws.happy.v1` | ticket、`start`、顺序 binary audio、`flush`、`stop` | `session.ready -> asr.vad_started -> asr.partial* -> asr.final -> session.completed` | event sequence 严格递增；usage 只记摘要 |
| `tts.ws.happy.v1` | ticket、`start`、`text_append`、`text_commit` | `session.ready -> tts.audio_started -> tts.audio_chunk/binary* -> tts.audio_ended -> session.completed` | binary 的 `audio_sequence` 连续；已提交文本才允许 mark |
| `tts.http.happy.v1` | `POST /v1/tts/stream`、幂等 key | 首字节前成功状态及 metadata header，随后模拟音频 chunks | 首字节后不得返回 JSON success/error 混合体 |
| `control.session.cancel.v1` | 活跃 session 的重复 `DELETE` 或 WS `cancel` | `cancel_requested`/完成语义一致，终态为 `cancelled` | Provider cancel、reservation release、usage/audit 只发生一次 |
| `capabilities.scoped.v1` | 两个不同 Workspace 的 credential | 各自只得到允许的 canonical capability | 不泄露 mock profile、健康细节或另一 Workspace 信息 |

黄金路径中的 ASR/TTS 文本使用如 `synthetic phrase one` 的固定合成词，不代表真实语音识别质量。MockProvider 只验证协议与时序，不可用于模型质量判断。

## 4. 错误、背压与恢复 fixture

| Fixture ID | 触发条件 | 预期结果 |
| --- | --- | --- |
| `control.idempotency.same.v1` | 同 credential/operation/key/request digest 重复提交 | 返回同一语义 lease；仅一条 reservation/审计/Provider create |
| `control.idempotency.conflict.v1` | 同 key、不同 request digest | 标准 `invalid_request` 或冲突响应；无第二资源预留 |
| `stream.ticket.race.v1` | 同一 ticket 并行两次握手 | 仅一条连接消费成功；另一条为 `session_expired` 或等价拒绝 |
| `stream.start.invalid.v1` | ticket 与 start 的 session/task/audio 不匹配 | 未创建 Provider session；标准 `session.error` 后关闭 |
| `stream.audio.rate.v1` | 超过 byte/frame budget | 先 `flow.warning`；持续超限为 `session.error(code=invalid_audio)` 或受限错误并释放资源 |
| `provider.create.failure.v1` | MockProvider 建连前失败 | 标准 `provider_unavailable`；不发 `session.ready`；无活跃 lease 泄漏 |
| `provider.stream.failure.v1` | MockProvider 在 partial/音频段后失败 | `session.error` 或合规降级后终态；不重放已消费音频/已输出 segment |
| `provider.timeout.v1` | MockProvider 在虚拟时钟超过连接/流超时 | 正确 timeout 分类、circuit 观测、资源释放 |
| `stream.slow.consumer.v1` | 客户端停止读取输出 | bounded output 生效；无无界内存；按协议关闭/结束 |
| `stream.cancel.race.v1` | cancel 与 Provider final/ended 并发到达 | 只有一个终态，计量和释放幂等 |
| `state.ttl.recovery.v1` | Gateway 消失且 lease/ticket 到期 | 不重建 Provider/不重放；回收资源并写结束原因 |
| `policy.local_only.v1` | mock 无 local capability 的 local-only request | 标准 policy/unsupported 拒绝；无云/relay mock 建连 |

错误 fixture 必须同时断言 HTTP/WS 对外语义、内部 canonical code、状态机终态、reservation、usage event、audit event 和 metrics。仅断言状态码或日志字符串不算覆盖。

## 5. MockProvider 行为模型

MockProvider 的行为由 `mock-profile` 选择，所有延迟以虚拟时钟控制，不依赖真实网络或 sleep。它实现真实 Provider trait 的全部方法，并暴露测试专用的调用记录；生产 Gateway 不应加载 test-only profile。

| Profile | ASR 行为 | TTS 行为 | 主用途 |
| --- | --- | --- | --- |
| `happy` | 收到 N 个合成 frame 后按脚本返回 VAD/partial/final | commit 后按脚本返回 started/chunk/binary/ended | 主流程与 SDK fixture |
| `slow_first` | 延迟首 partial | 延迟首音频 | P95、超时、慢会话观测 |
| `create_reject` | `create_session` 立即返回可映射错误 | synthesize/start 立即拒绝 | 建连前回退/拒绝 |
| `fail_midstream` | 已产生 partial 后中断 | 已产生至少一个 chunk 后中断 | 流中错误与禁止重放 |
| `hang_until_cancel` | 不产生事件直到 cancel | 不产生 chunk 直到 cancel | 取消传播和 timeout |
| `quota_exhausted` | 返回上游配额错误 | 返回上游配额错误 | rate/quota 映射与熔断 |
| `protocol_violation` | 输出非法/乱序原生消息供 Adapter 检测 | 输出非法音频元数据 | Provider protocol error 与防御性解析 |

MockProvider 的脚本输入只能包含 canonical 事件和抽象错误，不模拟任何厂商 wire protocol。真实厂商 Adapter 的录制数据也必须先脱敏、再转换成同一 canonical fixture，原始请求/响应只能存放在受控、审批过的测试材料库。

## 6. Provider Contract Suite

所有 `AsrProvider`、`AsrSession`、`TtsProvider` 实现都必须通过以下套件。M1 由 MockProvider 先实现，M2 起每个真实 Adapter 在 sandbox 与录制 fixture 两种模式均执行。

1. capabilities 与请求协商一致；不支持项在 create 前明确拒绝。
2. `create -> send/next -> finish/cancel` 的调用顺序完整；重复 cancel/finish 安全。
3. Provider 原生事件被转换为合法 canonical event，字段、sequence、session ID 和 trace ID 不泄漏/不伪造。
4. 原生错误被映射到模块 12 分类，不包含密钥、URL、音频或完整文本。
5. 超时、连接拒绝、半关闭、流中失败和取消均释放资源且不阻塞 runtime。
6. Adapter 指标只含允许的低基数维度；日志/trace 不含原文或长期凭证。

## 7. 租户、状态和用量测试矩阵

| 领域 | 最低测试 | 成功条件 |
| --- | --- | --- |
| 组织/空间隔离 | 资源 ID 猜测、cursor 复用、session 查/取消、capability 查询 | 返回 404/授权拒绝；没有存在性、用量、诊断或缓存泄漏 |
| credential | hash 验证、撤销、轮换、范围收窄 | 撤销立刻阻断新会话；旧 ticket 不扩大权限 |
| ticket | 单次消费、过期、绑定 session/channel、并行握手 | 仅合法连接进入 Provider；access log 不出现 token |
| reservation | 创建失败、重复请求、Provider create 失败、cancel、TTL | 每个 reservation 最终 release 或 settle 一次 |
| usage/outbox | terminal event、重放、重复 consumer、失败补偿 | append-only 去重；estimated 与 observed 明确；不重复扣减 |
| audit | 创建、取消、拒绝、ticket 失败、配置载入 | actor、scope、request/trace、原因和结果完整且不含密钥 |
| observability | 错误/慢流/忙、Provider 失败 | metric/tag 不出现 session ID、文本、音频字节内容 |

## 8. 兼容性 fixture 与变更纪律

每次修改 OpenAPI/AsyncAPI 或 canonical type 时必须运行：旧 fixture 反序列化、旧客户端容忍未知可选字段/事件、请求安全枚举拒绝未知值、schema diff 和 golden output diff。`v1` fixture 不得原地修改语义；修复只可新增 fixture 或新增更精确的断言。确需改变已有预期时，必须记录兼容性分类、迁移路径和新主版本策略。

## 9. M1 完成定义

M1 至少需要：6 个黄金路径 fixture、12 个错误/韧性 fixture、MockProvider 的全部 7 个 profile、Provider Contract Suite、租户/状态/用量矩阵的自动化入口，以及对每个 fixture 的 trace/metric/持久化断言。没有真实 Provider 并不降低这些要求；真实 Provider 只是在 M2 增加外部 probe 证据。
