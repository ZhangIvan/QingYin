# QingYin 模块 20：公开接口字段与交互时序

版本：v0.2
目标：冻结可转写为 OpenAPI 3.1 与 AsyncAPI 3.x 的核心字段和时序，避免后端、SDK 与前端分别理解同一接口。

## 1. 通用组件

| 组件 | 字段与规则 |
| --- | --- |
| `ResourceId` | 不可预测、全局唯一字符串；资源前缀表达类型，例如 `ses_`、`evt_`、`op_`，前缀不承载授权信息 |
| `TimestampMs` | UTC Unix 毫秒，仅由服务端产生的时间用于审计/超时 |
| `ApiError` | `code`、`category`、`message`、`retryable`、`retry_after_ms?`、`diagnostic_id?`，取值受模块 12 约束 |
| `Page` | `items`、`next_cursor?`；cursor 不透明且绑定查询主体/过滤条件 |
| `Operation` | `operation_id`、`status`、`created_at_ms`、`updated_at_ms`、`result_ref?`、`error?` |
| `AudioSpec` | `codec`、`container?`、`sample_rate_hz`、`channels`、`frame_ms?`；所有字段需与会话协商能力相交 |
| `PolicyPreference` | `profile`、`data_residency?`、`provider_hint?`；只是偏好，不能放宽租户硬约束 |

未声明的字段不能作为必需语义使用。所有 ID、cursor、ticket、诊断 ID 均为不透明值，客户端不得解析内部结构。

## 2. 创建会话

### 2.1 `POST /v1/sessions`

请求体 `CreateSessionRequest`：

| 字段 | 必填 | 规则 |
| --- | --- | --- |
| `task` | 是 | `asr|tts|realtime` |
| `mode` | 是 | `streaming|realtime|one_shot`；任务不支持的组合拒绝 |
| `language` | 否 | BCP-47 风格语言标识；缺省表示可自动选择的策略范围 |
| `audio` | ASR/Realtime 是 | `AudioSpec`；必须是客户端实际能传输的参数 |
| `output_audio` | TTS/Realtime 可选 | 期望的 `AudioSpec`，最终以协商结果为准 |
| `features` | 否 | `interim_results`、`punctuation`、`timestamps`、`marks` 等规范布尔/枚举 |
| `policy` | 否 | `PolicyPreference`，不得包含厂商凭证或内部 Provider 名称 |
| `client` | 是 | `platform`、`sdk_version?`、`app_version?`；用于兼容与能力选择 |
| `metadata` | 否 | 限大小、限键名的业务关联标签；不得存受限文本/密钥 |

请求头必须包含 `Idempotency-Key`。同一租户、操作和请求摘要下重复提交返回同一语义结果；摘要不同返回 `invalid_request`。

响应体 `SessionLease`：

| 字段 | 必填 | 规则 |
| --- | --- | --- |
| `session_id` | 是 | QingYin session ID |
| `status` | 是 | 初始为 `leased|connecting|ready`，不暴露内部 Provider 状态 |
| `transport_mode` | 是 | `direct_sdk|relay|edge|local` |
| `expires_at_ms` | 是 | ticket/lease 最晚有效时间 |
| `accepted_audio` | 条件 | 最终输入 `AudioSpec` |
| `accepted_output_audio` | 条件 | 最终输出 `AudioSpec` |
| `capabilities` | 是 | 对该会话实际允许的规范特性集合 |
| `connect` | 条件 | Relay/Edge URL 或 Direct SDK 连接说明；仅含短期不透明 ticket |
| `trace_id` | 是 | 诊断关联，不是权限凭证 |

`connect` 绝不包含 Provider 长期密钥、可复用签名或真实 Provider 的管理凭证。Direct 需要的连接细节只对受控 SDK 可见。

### 2.2 会话查询与取消

`GET /v1/sessions/{session_id}` 返回租户可见的 `session_id`、`status`、`task`、`transport_mode`、`created_at_ms`、`updated_at_ms`、`usage_summary?`、`terminal_reason?`、`trace_id`。不返回原始音频、完整文本、Provider 凭证或未授权诊断。

`DELETE /v1/sessions/{session_id}` 返回 `session_id`、`status=cancel_requested|completed`、`accepted_at_ms`。重复取消视为成功；已完成会话不重新开启。

## 3. 一次性 TTS

### 3.1 `POST /v1/tts/stream`

请求 `TtsStreamRequest`：

| 字段 | 必填 | 规则 |
| --- | --- | --- |
| `text` | 是 | 服务端规范化前后的最大长度均受能力/策略限制 |
| `voice` | 否 | QingYin voice profile，不直接使用厂商 voice ID |
| `audio` | 否 | 期望输出 `AudioSpec` |
| `speech` | 否 | `speed`、`pitch`、`volume`、`style?`，范围由 voice profile 限制 |
| `policy` | 否 | 仅合法偏好 |
| `marks` | 否 | 是否需要文本-音频对齐 mark |

成功时返回协商后的 audio response；响应头含 `X-QingYin-Session-Id`、`X-QingYin-Audio-Codec`、`X-QingYin-Audio-Sample-Rate`、`X-Request-Id`。失败发生在首字节前使用 HTTP `ApiError`；首字节后使用已声明的流结束语义与可选 trailer/metadata，且服务端记录规范错误。

## 4. WebSocket 流

### 4.1 连接前提

WebSocket URL 只承载路径和必要非敏感参数。服务端客户端使用 `Authorization: Bearer <one-time-ticket>`；浏览器/Mobile 由受控 SDK 使用 `Sec-WebSocket-Protocol: qingyin.v1, qy.ticket.<opaque-token>` 传递一次性 ticket，Gateway、反向代理与 access log 必须完整脱敏该子协议。URL query 不得传递长期项目密钥，也不作为 M1 的 ticket 通道。连接成功后首个文本帧必须是 `start`：

| 字段 | 必填 | 规则 |
| --- | --- | --- |
| `type` | 是 | 固定 `start` |
| `event_id` | 是 | 客户端生成、会话内去重 |
| `session_id` | 是 | 必须与 ticket 匹配 |
| `audio` | ASR/Realtime 是 | 最终协商的 `AudioSpec` |
| `features` | 否 | 不得超出 `SessionLease.capabilities` |

服务端在完全验证后发送 `session.ready`。在此之前的音频或文本 append 必须被拒绝，不允许进入 Provider。

### 4.2 ASR 控制与音频

| 客户端帧 | 必填字段 | 行为 |
| --- | --- | --- |
| binary audio | 按协商 AudioSpec | `audio_sequence` 通过二进制帧顺序或包头定义；不得乱序/超速 |
| `flush` | `type`、`event_id` | 请求尽快处理已发送音频，不等同 final |
| `stop` | `type`、`event_id` | 结束输入并等待 final/completed |
| `cancel` | `type`、`event_id` | 停止输入、释放资源，幂等 |
| `ping` | `type`、`event_id` | 保活；服务端回 `pong` |

服务端只发送模块 12 的 `asr.*`、`flow.*` 和 `session.*` 事件。每个 `asr.partial/final` 带 `utterance_id`；final_update 必须带 `replaces_event_id`。

### 4.3 增量 TTS

| 客户端帧 | 必填字段 | 行为 |
| --- | --- | --- |
| `text_append` | `event_id`、`text` | 临时文本，不得生成不可撤销音频 |
| `text_commit` | `event_id`、`commit_id`、`text?` | 提交可合成边界；同一 commit 去重 |
| `text_replace` | `event_id`、`target_commit_id`、`text` | 仅允许尚未播放/合成的内容，过期则返回 validation error |
| `cancel` | `event_id` | 停止未播放片段并结束会话 |

服务端使用 `tts.audio_started`、`tts.audio_chunk`、binary 音频、`tts.mark`、`tts.audio_ended`。音频帧必须与 `audio_id`、`audio_sequence` 和 `segment_id` 关联。

### 4.4 Realtime 双工

Realtime 在同一会话中并行使用 ASR binary audio、文本控制与 TTS 音频，但 sequence 空间独立：`control_sequence`、`input_audio_sequence`、`output_audio_sequence`。客户端通过 `turn.commit` 表示用户轮次结束；系统只能在策略允许的情况下触发 TTS。barge-in 发生时，客户端发送 `output.cancel`，服务端停止未播放 TTS 并将状态写入审计。

## 5. Direct 与 Relay 时序

### Direct

```text
App Backend -> QingYin: create session
QingYin -> App/SDK: SessionLease + short-lived ticket
SDK -> selected Provider: provider-native connection
SDK -> App: QingYin canonical events
SDK -> QingYin: minimal usage/close telemetry
```

应用只与 QingYin SessionLease 和 canonical events 交互。Direct 建连失败可在未发送音频前创建新 lease；发送音频后遵守 utterance/segment 边界，不做隐式重放。

### Relay/Local/Edge

```text
App/SDK -> QingYin or assigned Edge: WS start + binary/control frames
QingYin/Edge -> Provider or Worker: adapted stream
QingYin/Edge -> App/SDK: canonical events + audio
```

Relay、Local、Edge 的公开帧格式完全一致；差异只能体现在 `transport_mode`、时延和可用能力上。

## 6. 规范冻结验收

每项字段必须有：JSON Schema、合法/非法示例、最小/最大边界、权限要求、限流 scope、隐私等级、错误映射与 fixture。全链路 fixture 要覆盖 Direct、Relay、Local、ticket 过期、重复请求、乱序帧、Provider 失败、cancel、降级和版本兼容。完成这些产物后，模块 13 才能生成正式 OpenAPI/AsyncAPI 文件并进入实现。
