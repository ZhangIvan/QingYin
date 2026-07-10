# QingYin 模块 01：统一协议与会话

版本：v0.2
所有公开协议以 `v1` 命名空间发布。字段只增不改；厂商字段不得透传到公开事件。

## 1. API 面

| 接口 | 用途 | 传输 |
| --- | --- | --- |
| `POST /v1/sessions` | 获取路由结果、会话票据和数据面信息 | HTTPS JSON |
| `WS /v1/asr/stream` | Relay/Local 实时 ASR | WebSocket binary + JSON |
| `POST /v1/tts/stream` | 一次性文本的音频流 | HTTP chunked |
| `WS /v1/tts/stream` | LLM 文本增量到音频增量 | WebSocket |
| `WS /v1/realtime` | ASR/文本/TTS 的双工会话 | WebSocket |
| `GET /v1/capabilities` | 租户可见能力，不含内部健康细节 | HTTPS JSON |

`POST /v1/sessions` 返回 `session_id`、`transport_mode`、到期时间、可使用的 codec 和一次性连接信息。它不返回供应商长期凭证，也不保证暴露真实 Provider 名称。

## 2. 统一请求模型

```json
{
  "task": "asr",
  "mode": "streaming",
  "language": "zh-CN",
  "audio": {"codec": "opus", "container": "ogg", "sample_rate_hz": 16000, "channels": 1},
  "features": {"interim_results": true, "punctuation": true, "timestamps": false},
  "policy": {"profile": "balanced", "data_residency": "cloud_allowed"},
  "client": {"platform": "web", "sdk_version": "0.1.0"}
}
```

规范枚举：`task` 为 `asr|tts|realtime`；`policy.profile` 为 `latency_first|quality_first|cost_first|privacy_first|bandwidth_first|balanced`；`data_residency` 为 `cloud_allowed|local_only|named_region`。未知枚举必须被明确拒绝，不能静默按默认值处理。

## 3. 统一事件信封

```json
{
  "type": "asr.partial",
  "event_id": "evt_01J...",
  "session_id": "ses_01J...",
  "sequence": 42,
  "occurred_at_ms": 1783648000123,
  "trace_id": "tr_01J...",
  "data": {}
}
```

事件类型：

- 生命周期：`session.ready`、`session.degraded`、`session.completed`、`session.error`。
- ASR：`asr.vad_started`、`asr.vad_ended`、`asr.partial`、`asr.final`、`asr.final_update`。
- TTS：`tts.audio_started`、`tts.audio_chunk`、`tts.mark`、`tts.audio_ended`。
- 流控：`flow.warning`、`flow.busy`、`flow.retrying`。

`sequence` 在一个会话内单调递增。客户端发现缺号时只记录诊断信息，不得重放实时音频；重连后从新的 `session_id` 开始，必要时带 `resume_from_utterance_id`。

## 4. 会话状态机

```text
created -> authorized -> routing -> leased -> connecting -> active
active -> draining -> completed
active -> retrying -> active
any nonterminal -> cancelled | expired | failed
```

- `routing` 只做无副作用筛选和评分；`leased` 才消耗 Provider 并发配额。
- `connecting` 有短超时；成功后才通知 `session.ready`。
- ASR Provider 失败时，Gateway 只能在下一个 utterance 建立新会话，或让客户端重连。已发送音频的重放窗口默认关闭，只有客户端明确允许且具备去重 ID 时才开启。
- TTS 在尚未播放的 segment 边界可切换；已播放音频绝不替换。

## 5. 取消、心跳与背压

- 客户端控制帧：`start`、`audio`、`flush`、`stop`、`cancel`、`ping`。
- 服务端必须在 1 秒内传播取消到 Provider/Worker 并释放租约。
- 默认心跳 20 秒，连续两次未响应则关闭并写入原因码。
- 网关以 byte budget 和 frame budget 控制读速；超出时先 `flow.warning`，仍超出则 `session.error(code=audio_rate_exceeded)`。
- `busy` 必须携带 `retry_after_ms`。它是容量保护结果，不是 5xx。

## 6. SDK 边界

SDK 对应用暴露统一事件和重试语义；在 Direct 模式下它内部实现厂商连接、短期凭证使用和事件映射。SDK 不持久化云密钥，不将完整音频或转写默认上报，遥测只发送采样率、字节数、时延和原因码。

契约产物：JSON Schema、OpenAPI（HTTP）、AsyncAPI（WebSocket）、golden event fixtures。所有 Adapter 和 SDK 必须运行同一套 fixtures。
