# QingYin 模块 24：实时对话与 LLM 编排

版本：v0.2
目标：当产品启用 AI 实时对话时，以独立编排层连接 ASR、可选 LLM 和 TTS；纯 ASR/TTS 会话不加载该能力，也不伪造 LLM 事件。

## 1. 回合状态机

```text
listening -> recognizing -> user_turn_final
  -> reasoning/streaming_text -> speaking -> listening
any active stage -> interrupted | cancelled | failed | completed
```

编排层只接收 ASR final 或策略允许的稳定 partial；LLM 文本以可提交片段发送给 TTS；TTS 只播放已提交片段。每个 turn 使用独立 `turn_id`、`llm_turn_id`、`tts_segment_id` 关联，避免跨轮次取消或计费混乱。

## 2. LLM Provider 与事件

LLM 是独立的 `ConversationModelProvider`，必须实现能力快照、区域/隐私过滤、并发/Token/成本准入、流式文本、工具调用、取消、错误映射、熔断和用量事件。前端不持有 LLM 厂商凭证。

规范事件为：`llm.turn_started`、`llm.text_delta`、`llm.tool_call`、`llm.turn_completed`、`llm.turn_cancelled`。调试台只对授权用户显示文本长度、时延、token/成本摘要和脱敏内容；完整 prompt、tool 参数和模型输出遵从模块 23 L5 规则。

## 3. Barge-in、降级与验收

用户新语音触发 barge-in 时，编排器停止未播放 TTS、取消可取消 LLM 请求、记录已输出边界，然后回到 listening。不能撤回已播放音频或已执行工具。

降级顺序：减少非关键事件 -> 停止 TTS 仅返回文本 -> 禁用 LLM 回到 ASR/TTS -> 允许时切备用 LLM -> busy。任何降级需 `session.degraded`，并且不破坏 `local_only`、地域和预算边界。

验收要求：回合事件顺序正确；barge-in 不遗留播放或计费泄漏；LLM 失败可按策略降级；工具/内容/成本不跨 Workspace；调试台仅显示被授权的数据等级。
