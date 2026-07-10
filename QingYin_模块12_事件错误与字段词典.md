# QingYin 模块 12：事件、错误与字段词典

版本：v0.2
目标：为 Gateway、SDK、Provider Adapter、Worker、控制台和测试提供唯一的规范事件语言。厂商原始字段只保留在受限诊断记录中，不能成为业务契约。

## 1. 事件信封

所有控制事件使用同一信封；音频二进制帧由最近的 `tts.audio_started` 元数据说明其 codec、采样率、声道和顺序。

| 字段 | 类型 | 必填 | 规则 |
| --- | --- | --- | --- |
| `type` | string | 是 | 稳定命名空间，例如 `asr.partial` |
| `event_id` | string | 是 | 全局唯一，仅用于诊断与去重 |
| `session_id` | string | 是 | QingYin 会话 ID，不复用厂商 request ID |
| `sequence` | integer | 是 | 会话内严格递增；音频帧使用独立 `audio_sequence` |
| `occurred_at_ms` | integer | 是 | 服务端产生事件的 Unix 毫秒时间 |
| `trace_id` | string | 是 | 跨 Gateway、Adapter、Worker 的关联 ID |
| `data` | object | 是 | 仅承载对应 `type` 的已定义字段 |
| `schema_version` | string | 是 | 事件 schema 版本，初始 `v1` |

客户端必须以 `type` 判断事件语义，不能依赖字段存在与否猜测类型。

## 2. 生命周期事件

| 事件 | 必填 data | 语义 |
| --- | --- | --- |
| `session.ready` | `transport_mode`、`capabilities`、`expires_at_ms` | 已完成授权、路由和底层建连，可开始发送/接收 |
| `session.degraded` | `reason`、`impact`、`recovery_action` | 会话仍可用但能力、Provider 或质量已变化 |
| `session.completed` | `reason`、`usage_summary` | 正常 stop、finish 或完整播放结束 |
| `session.error` | `error` | 不可继续的规范错误；随后关闭或等待客户端明确动作 |
| `flow.warning` | `resource`、`current`、`limit` | 仍可恢复的速率/队列告警 |
| `flow.busy` | `scope`、`retry_after_ms`、`reason` | 新工作不被接受；不是内部 5xx |

## 3. LLM 事件（仅 Realtime 编排启用）

`llm.turn_started`、`llm.text_delta`、`llm.tool_call`、`llm.turn_completed`、`llm.turn_cancelled` 均必须关联 `turn_id`，并遵循模块 24 的权限、留存和取消边界。纯 ASR/TTS 会话不产生这些事件。

## 4. ASR 事件字段

| 事件 | 必填 data | 约束 |
| --- | --- | --- |
| `asr.vad_started` | `utterance_id`、`start_ms` | 同一 utterance 只出现一次 |
| `asr.vad_ended` | `utterance_id`、`end_ms` | 可在 final 前出现 |
| `asr.partial` | `utterance_id`、`text`、`start_ms`、`end_ms`、`stable_prefix_length` | 文本可回改；`stable_prefix_length` 之前不得改变 |
| `asr.final` | `utterance_id`、`text`、`start_ms`、`end_ms`、`confidence_state` | 该 utterance 的当前最终结果 |
| `asr.final_update` | `utterance_id`、`replaces_event_id`、`text`、`reason` | 仅在声明的增强窗口内替换 final |

可选字段包括 `words`、`language`、`speaker`、`emotion`、`events`。未被 Provider 支持时字段缺省，不能伪造默认值。

## 5. TTS 事件与音频帧

| 事件 | 必填 data | 约束 |
| --- | --- | --- |
| `tts.audio_started` | `audio_id`、`codec`、`container`、`sample_rate_hz`、`channels` | 随后的 binary frame 均绑定此 `audio_id` |
| `tts.audio_chunk` | `audio_id`、`audio_sequence`、`byte_length`、`segment_id` | HTTP chunk 模式可省略控制事件，但 metadata 必须等价可得 |
| `tts.mark` | `segment_id`、`text_start`、`text_end`、`audio_offset_ms` | 标记只对应已提交文本，不对应 LLM 未稳定 token |
| `tts.audio_ended` | `audio_id`、`reason`、`duration_ms` | 正常结束、取消、上游失败需区分 |

`audio_sequence` 只表示传输顺序，不承诺等于播放时间。客户端检测缺帧时停止拼接并发出诊断；不应自行重排或猜测音频内容。

## 6. 规范错误词典

错误包含 `code`、`category`、`message`、`retryable`、`retry_after_ms`（如适用）、`scope` 和受限的 `diagnostic_id`。`message` 面向开发者，禁止包含密钥、原始音频或上游完整响应。

| code | category | 默认是否可重试 | 行为 |
| --- | --- | --- | --- |
| `auth_invalid` | auth | 否 | 更换 QingYin 凭证 |
| `permission_denied` | auth | 否 | 修改角色/策略 |
| `quota_exhausted` | quota | 是 | 等待额度或使用允许的候选路径 |
| `rate_limited` | quota | 是 | 遵守 `retry_after_ms` |
| `unsupported_capability` | validation | 否 | 更换任务、语言、codec 或 profile |
| `invalid_request` | validation | 否 | 修正 schema/参数 |
| `invalid_audio` | validation | 否 | 修正编码、采样率、帧顺序或实时率 |
| `policy_denied` | policy | 否 | 请求更低权限或联系管理员 |
| `session_expired` | session | 否 | 创建新会话 |
| `provider_unavailable` | upstream | 是 | 按会话回退规则重试 |
| `provider_timeout` | upstream | 视阶段 | 建连可重试；流中遵守边界回退 |
| `provider_protocol_error` | upstream | 视阶段 | 记录诊断并降级 Provider |
| `capacity_exceeded` | capacity | 是 | 等待或切换允许的数据面 |
| `cancelled` | session | 否 | 客户端/服务端主动结束 |
| `internal_error` | internal | 是 | 返回诊断 ID，触发告警 |

HTTP 请求使用相应的 4xx/5xx 状态表达入口失败；WebSocket/Direct SDK 始终发送规范 `session.error` 或 `flow.busy` 后按状态机关闭。业务方不应按厂商原始错误码编写逻辑。

## 7. 兼容性规则

- `v1` 只允许新增可选字段、新增事件类型和新增枚举值；不允许改变已有字段类型、语义或必填性。
- 客户端必须忽略未知可选字段和未知事件类型，同时保留其诊断信息；服务端必须拒绝未知的安全关键请求枚举。
- 废弃流程：标记 deprecated -> 在控制台和文档预告 -> 保持至少一个正式版本兼容 -> 发布移除版本与迁移说明。
- 厂商新增字段只能进入 Adapter 内部或转换为已定义的可选字段；不能绕过 schema 直接透传。

## 8. Fixture 与字段责任

每个事件和错误至少提供：正常、最小字段、最大字段、乱序/重复、未知字段、取消、超时和 Provider 映射 fixture。模块 09 的每个 Provider 探针都必须引用这些 fixture；前端设计稿中的状态文本、SDK 回调和指标维度也必须引用同一词典。
