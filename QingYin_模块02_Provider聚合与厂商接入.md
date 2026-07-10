# QingYin 模块 02：Provider 聚合、路由与厂商接入

版本：v0.2

## 1. Provider 契约

每个能力独立实现，不以“某厂商 SDK”作为系统抽象。一个供应商可以提供一个或多个 `Provider` 实例，例如 `tencent.asr.realtime` 和 `tencent.tts.realtime`。

```rust
pub trait AsrProvider: Send + Sync {
    fn capabilities(&self) -> ProviderCapabilities;
    async fn create_session(&self, request: CanonicalAsrRequest) -> Result<AsrSession, ProviderError>;
}

pub trait AsrSession: Send {
    async fn send_audio(&mut self, frame: AudioFrame) -> Result<(), ProviderError>;
    async fn next_event(&mut self) -> Option<Result<CanonicalEvent, ProviderError>>;
    async fn finish(&mut self) -> Result<(), ProviderError>;
    async fn cancel(&mut self);
}

pub trait TtsProvider: Send + Sync {
    fn capabilities(&self) -> ProviderCapabilities;
    async fn synthesize(&self, request: CanonicalTtsRequest) -> Result<AudioStream, ProviderError>;
}
```

Adapter 只处理认证、厂商连接、参数/编码映射、事件解析、错误翻译、取消和清理。路由、租户判断、计费、日志脱敏、跨厂商回退都在 Adapter 外完成。

## 2. 能力注册表

每个实例必须上报并持续更新：

```yaml
id: tencent.asr.realtime
kind: cloud
tasks: [asr]
transport: [relay, direct_sdk]
audio_in: [pcm_s16le, opus, mp3, aac]
languages: [zh-CN, yue, en]
features: [interim_results, punctuation, hotwords, timestamps]
limits:
  max_active: 0 # 0 表示从账户配额同步
  max_session_seconds: 0
health: healthy
cost_model: per_audio_minute
region: cn
```

配置分为三层：不可提交到仓库的凭证；环境级 Provider 配置；租户级允许列表和策略覆盖。能力声明需由探针验证，不能只靠静态 YAML。

## 3. 路由算法

先做硬过滤：任务、语言、音频格式可转换性、租户允许列表、数据驻留、可用区域、剩余并发、账户余额、熔断状态、Direct 安全性。

再评分：

```text
score = quality + locality + cache + direct_bonus
      - p95_latency - estimated_cost - error_rate - gateway_bytes - quota_pressure
```

评分参数由 `PolicyProfile` 控制，默认 `balanced`。同一会话将 Provider ID 固化在 lease 中；路由决策应记录候选集、过滤原因和最终分数，供审计而非暴露给客户端。

## 4. 故障转移

| 场景 | 策略 |
| --- | --- |
| 建连失败且未收到音频 | 尝试下一个候选 Provider |
| ASR 句中断流 | 向客户端发 `session.degraded`，在 utterance 边界重建；不承诺无缝续流 |
| TTS 首段失败 | 切换 Provider 后重合成未播放段 |
| TTS 中段失败 | 保留已播放段，切换下一个 segment；失败则明确结束 |
| 配额用尽/熔断 | 路由到候选项或 `flow.busy` |

禁止悄悄用不同厂商替换已经出声的 TTS 段，也禁止重放未知是否被接收的 ASR 帧。

## 5. 首批厂商清单与准入结论

| 厂商/通道 | 当前接入定位 | 初始优先级 | 设计注意点 |
| --- | --- | --- |
| 腾讯云 | 实时 ASR、实时/流式 TTS 候选 | P0 | WebSocket ASR 支持多编码；优先验证临时密钥与 Direct SDK |
| 阿里云/百炼 | 实时 ASR、TTS 候选 | P0 | 新旧接口并存；以当前账号可用的 WebSocket/鉴权模型为准 |
| 百度智能云 | 实时 ASR、流式 TTS 候选 | P0 | 两项均可走 WebSocket，先验证音频格式与租户并发 |
| 讯飞开放平台 | 实时转写、在线/流式 TTS 候选 | P0 | 必须隔离 appid/鉴权模式，验证商用账户配额 |
| MiniMax | 高质量流式 TTS 候选 | P0 | HTTP/WS 流式能力、音频格式、音色授权和用量规则单独探针 |
| 字节火山引擎 | ASR/TTS 候选 | P1 | 以当前控制台授权、实时协议、签名和区域配额完成准入后实现 |
| 小米 MiMo | 通用模型 ASR/TTS 候选 | P1 | 仅在企业账号和具体 API 可用后接入；验证 OpenAI 兼容层与音频流语义 |
| 小米小爱 AIVS | 设备生态通道 | P2/专案 | 面向设备与小爱协议，不等同通用云 ASR/TTS，单独 Adapter，不进入默认路由 |

这是一份接入计划而不是“所有厂商功能等价”的声明。腾讯官方实时 ASR 文档确认 WebSocket、实时返回、多编码与默认账号并发上限；阿里云文档确认实时 ASR WebSocket；百度文档确认实时 ASR 和流式 TTS WebSocket；讯飞公开目录包含实时转写和在线 TTS；MiniMax 文档公开流式 TTS。厂商功能、价格、配额和凭证机制会变化，M0 需要逐项探针验证。

## 6. Adapter 准入清单

一个 Adapter 合并前必须满足：

1. 支持 `create/start/send/finish/cancel` 的全流程和超时。
2. 全部厂商错误被映射到 QingYin `auth|quota|unsupported|invalid_audio|timeout|upstream|internal` 分类。
3. 支持测试模式和录制的脱敏 fixture；CI 不依赖生产密钥。
4. 参数、音频编码、文本限制、语音列表由 capability probe 生成或校验。
5. 指标含首包、最终结果、字节、错误、重连、估算成本。
6. 不允许日志写入原始密钥、授权 URL、完整用户音频或全文文本。

## 7. 参考资料

- [腾讯云实时语音识别 WebSocket](https://cloud.tencent.com/document/product/1093/48982)
- [阿里云实时语音识别 WebSocket](https://help.aliyun.com/zh/isi/developer-reference/websocket)
- [百度实时语音识别](https://cloud.baidu.com/doc/SPEECH/s/jlbxejt2i)
- [百度流式文本在线合成](https://cloud.baidu.com/doc/SPEECH/s/lm5xd63rn)
- [讯飞开放平台能力目录](https://www.xfyun.cn/doc/)
- [MiniMax WebSocket 流式 TTS 概览](https://platform.minimax.io/docs/api-reference/api-overview)
- [小米 MiMo ASR 文档](https://mimo.mi.com/docs/en-US/api/audio/Speech-Recognition)
- [小米小爱语音服务](https://developers.xiaoai.mi.com/voiceservice/index)
