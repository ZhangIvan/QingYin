# QingYin M1：Rust 核心骨架与运行规范

版本：v0.2
状态：实现准备基线，尚未创建业务代码
关联：模块 01、02、05、06、13、15、16；首条 ASR/TTS 纵向交付切片

## 1. M1 目标与非目标

M1 的目标是建立一个可测试的 Rust Gateway 骨架：它能按 `v1` 契约完成鉴权、会话准入、短期 ticket、MockProvider 流、取消、统一事件、基础计量和脱敏观测。该阶段的成功不是“已经接入云厂商”，而是任何未来 Adapter 都不能越过这些边界。

M1 必须交付：

- `POST /v1/sessions`、`GET/DELETE /v1/sessions/{session_id}`、`GET /v1/capabilities` 的公开控制面骨架。
- `WS /v1/asr/stream` 与 `WS /v1/tts/stream` 的 Mock 流；`POST /v1/tts/stream` 的一次性流式输出边界。
- 一个只用于开发/CI 的 Scripted MockProvider，覆盖正常、慢、限流、建连失败、流中失败和取消。
- Postgres 强一致状态接口、Redis TTL 状态接口及只限测试的内存实现。
- 多维 Admission 接口、可观察的预留/释放、统一错误和 trace 基础。

M1 不做真实云 Provider、Direct SDK、Local Worker、LLM 编排、真实音频转码、管理控制台或 L4/L5 捕获。Realtime 仅保持协议 fixture，不开放运行时路径。

## 2. Rust Workspace 与职责边界

计划的 workspace 目录是后续实现布局，不在本阶段预创建空 crate：

| crate / 目录 | 唯一职责 | 允许依赖 | 禁止依赖 |
| --- | --- | --- | --- |
| `qingyin-types` | ID、任务/状态枚举、Canonical event/error、AudioSpec、时间与 trace 类型 | `serde` 等基础库 | HTTP、数据库、厂商 SDK、tokio runtime |
| `qingyin-contract` | OpenAPI/AsyncAPI 对应 DTO、校验、错误序列化、fixture 反序列化 | `qingyin-types` | Provider、数据库、路由实现 |
| `qingyin-provider` | ASR/TTS trait、能力声明、Provider error、Adapter registry | `qingyin-types`、`qingyin-contract` | Gateway HTTP、租户授权、账务、厂商以外的业务逻辑 |
| `qingyin-state` | Repository/事务/Outbox/TTL state 的抽象与实现 | `qingyin-types` | WebSocket、厂商 SDK、请求 DTO |
| `qingyin-admission` | 限流、会话许可、预算预留、释放与拒绝原因 | `qingyin-types`、`qingyin-state` | HTTP handler、Provider 原生错误 |
| `qingyin-observe` | tracing 初始化、指标、脱敏字段、健康检查 | `qingyin-types` | 文本/音频原文持久化 |
| `qingyin-gateway` | axum/tokio 入口、认证 middleware、控制/WS handler、会话编排和优雅退出 | 前述内部 crate | 厂商 SDK、直接 SQL、业务密钥明文 |
| `qingyin-mock-provider` | Scripted ASR/TTS 行为、受控时序、故障注入 | `qingyin-provider`、`qingyin-types` | 网络、真实密钥、生产配置 |
| `qingyin-testkit` | fixture 读取、虚拟时钟、测试主体、断言与 fake telemetry | 全部接口 crate | 生产入口 |
| `migrations/` | 版本化控制面 schema 与不可逆变更说明 | 无 Rust 依赖 | 实时音频数据 |

依赖只能从 Gateway 向内。任何真实厂商 SDK 未来只能出现在独立 `qingyin-provider-<vendor>` crate，并只通过 `qingyin-provider` 暴露能力；它不能被 `qingyin-gateway` 直接引用。

## 3. 运行时与会话并发模型

Gateway 使用 tokio 管理连接，不在 async task 内执行模型推理、阻塞 DNS、同步数据库长查询或厂商 SDK 的阻塞调用。每个活跃 Relay 会话由受监督的会话组管理：

```text
WebSocket reader ----> bounded input channel ----> Provider session writer
Provider event reader -> bounded output channel ---> WebSocket writer
                         cancellation token
                         session lease / trace / metrics context
```

- 输入、输出和 Provider 事件均使用有界 channel；容量来自环境配置与容量卡，不在代码中写固定连接或字节上限。
- reader 达到 frame/byte budget 时先发 `flow.warning`；持续超限或下游不可写时进入标准错误与关闭流程，不能无界累积内存。
- 任一分支失败都触发同一 cancellation token；清理顺序为停止读取、通知 Provider、关闭输出、持久化终态、释放 reservation、写 outbox。
- `cancel`、ticket 过期、断开、超时和 Provider failure 使用同一幂等终止入口。M1 的验收目标是从收到 cancel 到 MockProvider 清理并释放许可不超过 1 秒。
- 优雅退出停止新握手、向已建连 session 发送可行动通知并在 drain deadline 后强制终止；实例不接受新的 lease 后才能下线。

M1 对真实音频只验证长度、帧顺序和协商 AudioSpec；MockProvider 不解码或持久化音频。实际转码、VAD 和本地模型属于后续数据面/Worker 阶段。

## 4. 状态、ticket 与事务边界

| 数据类别 | M1 生产候选实现 | 测试实现 | 规则 |
| --- | --- | --- | --- |
| Organization/Workspace/Project/Environment、credential 元数据、session、reservation、usage event、audit/outbox | PostgreSQL | InMemoryStateStore | 生产状态的唯一事实来源；所有记录带完整归属链 |
| ticket、连接心跳、令牌桶、活跃许可、幂等短缓存 | Redis | InMemoryTtlStore | 有 TTL；缓存丢失不得跳过授权或重复计费 |
| 配置快照、能力快照 | 版本化文件/控制面表 | 固定 fixture | 仅通过 snapshot ID 引用，不在会话中查可变全局配置 |

会话创建的强一致边界：认证后验证完整资源链与策略，确定候选 MockProvider/transport，随后在一个数据库事务中写入 `session(status=leased)`、`route_snapshot`、`session_reservation`、`audit_event` 与 outbox。提交成功后才签发 ticket；ticket 写入失败时必须把 session 标记为失败并释放 reservation，或由短时补偿任务完成同等效果。

M1 ticket 采用不可猜测的一次性不透明随机值。Redis 只保存 ticket hash、session ID、绑定主体摘要、允许的 channel、过期时间和 `unused/consumed` 状态；不保存 Provider 凭证。WebSocket 握手原子消费 ticket 后才接受 `start`。浏览器传输使用受控 SDK 的 `Sec-WebSocket-Protocol` ticket 子协议，并由 access log 完整脱敏；服务端客户端优先使用 `Authorization` Header。禁止在 URL query 传递长期项目密钥。

## 5. 鉴权、准入和控制流

`POST /v1/sessions` 的 M1 处理顺序固定如下：

```text
request id -> credential parse -> hash verify/revocation check -> principal context
-> validate DTO -> resolve organization/workspace/project/environment
-> resolve policy and capability snapshot -> admission reserve
-> persist session/route/reservation/audit/outbox -> issue lease/ticket -> response
```

- Project credential 只映射到一个允许范围；请求 body、metadata、header 均不能指定或覆盖 Workspace。
- `Idempotency-Key` 的 scope 为 credential + operation + request digest；同 key 不同摘要返回标准冲突，不会产生第二个 reservation。
- Admission 依次检查 API QPS、连接/活跃 session、Gateway bytes、Provider capacity、预算；每个拒绝都产生可观测原因和 `retry_after_ms`。
- M1 route 只有 `mock.asr.realtime` 和 `mock.tts.streaming` 两个候选；`local_only` 没有 mock local 能力时返回明确的 policy/unsupported 错误，绝不伪装成云可用。
- 对可接受连接，WS 首帧 `start` 验证 session/ticket/task/AudioSpec 后创建 Provider session；Provider 成功创建后才发 `session.ready`。

## 6. 配置与密钥规范

部署配置按 schema version 管理，采用“公开配置 + secret reference”两层。配置文件和日志中只能出现 `secret_ref`，不得出现 API Key、私钥、数据库口令、Provider token 或可复用 ticket。

| 配置域 | 最小字段 | M1 校验 |
| --- | --- | --- |
| `runtime` | `schema_version`、`environment`、`instance_id`、listen 地址、shutdown deadline | 未知版本/不安全 listen 配置失败启动 |
| `public_api` | origin/host allow-list、请求体/帧大小策略、CORS、API version | browser 允许范围明确；不支持通配敏感 origin |
| `state` | Postgres/Redis `secret_ref`、超时、TTL policy | 生产 profile 不允许内存 state；TTL 均有上限 |
| `security` | credential pepper `secret_ref`、ticket TTL、日志脱敏规则、管理员 bootstrap reference | ticket TTL 短且一次性；禁止 secret inline |
| `admission` | 容量卡引用、策略 snapshot、各闸门配置引用 | 无有效容量/策略 snapshot 时只能开发模式启动 |
| `providers` | `mock` 行为 profile、能力 snapshot reference、enabled flag | M1 仅允许 mock；禁止 vendor credential 字段 |
| `observability` | OTLP/Prometheus endpoint reference、trace sampling、metric labels | 禁止 session ID/文本/音频作为 metric label |
| `features` | `asr_ws`、`tts_ws`、`tts_http`、`realtime` | M1 `realtime=false` 且不可用配置绕过 |

配置加载只发生在启动或受控 reload 边界。每次加载生成 `config_snapshot_id` 和内容 hash，写入健康/审计；会话创建时固化 snapshot ID。热更新不能直接改变已有会话的 Provider、票据范围或租户策略。

## 7. M1 公开行为边界

| 接口/通道 | M1 行为 | 明确不做 |
| --- | --- | --- |
| `GET /v1/capabilities` | 返回认证范围内的 mock canonical capability | 不暴露内部健康、分数、密钥或真实厂商名 |
| `POST /v1/sessions` | ASR/TTS session lease、ticket、trace ID、协商 AudioSpec | Direct connection、跨 Provider fallback、未验证本地路由 |
| `WS /v1/asr/stream` | `start`、binary frame、`flush/stop/cancel/ping`、标准 ASR 事件 | 音频解码、真实识别、音频重放 |
| `WS /v1/tts/stream` | `start`、`text_append/commit/replace/cancel`、TTS event 与模拟二进制块 | 真实音色、已播放段替换 |
| `POST /v1/tts/stream` | 一次性 text 到受控模拟音频流，首字节前错误为 HTTP JSON | 首字节后将错误伪装为完整成功 |
| `GET/DELETE /v1/sessions/{id}` | 租户可见状态、取消和终态摘要 | 原文音频/文本、Provider 原生数据 |

## 8. M1 实现完成定义

实现开始前，必须先为每个 crate 建立职责/依赖检查和测试目录；没有通过 fixture 的类型不可公开。完成 M1 的判断以 `QingYin_M1_契约Fixture与MockProvider规范.md`、`QingYin_M1_实施Backlog与CI门禁.md` 的测试证据为准，而不是以服务能启动为准。
