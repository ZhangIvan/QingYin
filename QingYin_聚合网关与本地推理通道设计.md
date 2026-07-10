# QingYin 聚合网关与本地推理通道设计

版本：v0.1
日期：2026-07-09
约束：2C8G2M 可运行、支持多厂商云服务、本地小模型可插拔、对业务暴露统一协议

> 定位说明：本文保留 2C8G2M 作为低配参考场景；v0.2 模块文档不以该规格为系统上限，统一采用 `QingYin_模块07_能力规划与容量模型.md` 推导各环境容量。

## 1. 核心结论

QingYin 不应该把所有音频都强制经过自己的 ECS 中转。正确设计是：

```text
控制面聚合：必须经过 QingYin
数据面传输：按场景选择直连云厂商、QingYin 压缩中转、边缘 Relay、本地推理
模型能力：云厂商和本地小模型都作为 Provider 接入统一路由
```

核心原则：

1. 业务侧只调用 QingYin 统一 API，不感知厂商差异。
2. QingYin 内部用 Provider Adapter 屏蔽不同厂商的鉴权、协议、参数和事件格式。
3. 2Mbps ECS 不承担大规模音频转发，默认优先直连或压缩转发。
4. 本地小模型不是另一套系统，而是 `local` Provider。
5. 所有 Provider 必须被统一限流、熔断、观测、计费和降级。

## 2. 总体架构

```text
Client / SDK
   |
   | QingYin Unified API
   v
QingYin Gateway
   ├─ Auth / Tenant / Quota
   ├─ Session Manager
   ├─ Capability Registry
   ├─ Provider Router
   ├─ Policy Engine
   ├─ Adapter Runtime
   ├─ Local Inference Runtime
   └─ Metrics / Audit

Provider Adapters
   ├─ Tencent ASR/TTS Adapter
   ├─ Aliyun ASR/TTS Adapter
   ├─ Volcengine ASR/TTS Adapter
   ├─ Baidu ASR/TTS Adapter
   ├─ Local sherpa-onnx Adapter
   ├─ Local SenseVoice Adapter
   └─ Local MeloTTS/Kokoro/Piper Adapter

Data Plane
   ├─ Direct-to-Provider
   ├─ QingYin Relay
   ├─ Edge Relay
   └─ Local Inference
```

## 3. 统一协议与厂商协议分离

### 3.1 外部统一协议

业务只看到 QingYin 协议：

```text
WS   /v1/asr/stream
POST /v1/tts/stream
WS   /v1/realtime
POST /v1/sessions
```

外部事件统一：

```json
{
  "type": "partial",
  "session_id": "s_123",
  "utterance_id": "u_1",
  "text": "你好",
  "start_ms": 120,
  "end_ms": 700,
  "stable": false,
  "provider": "hidden"
}
```

厂商事件统一映射为：

```text
ready
vad_start
vad_end
partial
final
final_update
audio_chunk
mark
error
completed
```

### 3.2 内部 Provider 接口

Rust 层建议定义 trait：

```rust
trait AsrProvider {
    async fn start(&self, req: AsrStartRequest) -> Result<AsrSession>;
}

trait AsrSession {
    async fn send_audio(&mut self, chunk: AudioChunk) -> Result<()>;
    async fn next_event(&mut self) -> Option<Result<AsrEvent>>;
    async fn finish(&mut self) -> Result<()>;
    async fn cancel(&mut self);
}

trait TtsProvider {
    async fn stream(&self, req: TtsRequest) -> Result<TtsAudioStream>;
}
```

每个厂商适配器只负责：

- 签名。
- 建连。
- 参数映射。
- 音频格式映射。
- 事件解析。
- 错误码归一化。
- 取消和超时。

不要让业务层直接调用厂商 SDK。

## 4. Provider 能力注册表

每个 Provider 启动时注册能力：

```yaml
providers:
  tencent_asr_realtime:
    kind: cloud_asr
    streaming: true
    direct_client: true
    relay: true
    codecs_in: [opus, pcm, wav, mp3, aac]
    codecs_out: [json]
    languages: [zh, yue, en, ja, ko]
    supports_hotwords: true
    supports_word_timestamp: true
    max_concurrency: 200
    cost_level: medium
    quality_level: high
    latency_level: low

  local_sherpa_asr:
    kind: local_asr
    streaming: true
    direct_client: false
    relay: false
    codecs_in: [pcm]
    languages: [zh, en]
    max_concurrency: 2
    cost_level: very_low
    quality_level: medium
    latency_level: low

  local_melo_tts:
    kind: local_tts
    streaming: engineering_chunked
    direct_client: false
    relay: false
    codecs_out: [pcm, opus]
    max_concurrency: 1
    cacheable: true
```

能力注册表必须包含：

- 支持的任务：ASR、TTS、Realtime。
- 支持的语言、方言、行业模型。
- 支持的输入/输出编码。
- 是否支持客户端直连。
- 是否支持热词、词级时间戳、情感、SSML。
- 默认并发上限。
- 当前健康状态。
- 当前配额剩余。
- 最近 P95/P99 延迟。
- 成本权重。
- 质量评分。

## 5. 路由策略

### 5.1 硬过滤

先排除不满足需求的 Provider：

```text
任务类型不匹配 -> 排除
语言不支持 -> 排除
编码不支持且不能转码 -> 排除
隐私要求 local_only -> 排除云 Provider
带宽策略 no_relay -> 排除必须中转的 Provider
并发满 -> 排除
熔断中 -> 排除
```

### 5.2 评分选择

剩余 Provider 按策略打分：

```text
score =
  quality_weight * quality_score
  - latency_weight * p95_latency
  - cost_weight * estimated_cost
  - bandwidth_weight * estimated_gateway_bytes
  - risk_weight * recent_error_rate
  + locality_bonus
  + cache_hit_bonus
```

典型策略：

| 策略 | 行为 |
| --- | --- |
| `cost_first` | 优先本地小模型和低价云服务 |
| `latency_first` | 优先低 P95、少中转、直连 |
| `quality_first` | 优先大模型云服务 |
| `privacy_first` | 只走本地或私有化 Provider |
| `bandwidth_first` | 优先客户端直连、Opus、缓存 |
| `balanced` | 综合成本、质量、延迟 |

### 5.3 限流与熔断

每个 Provider 独立维护：

```text
active_sessions
tokens_per_second
daily_quota
p95_latency
error_rate
consecutive_failures
circuit_state
```

状态：

- `healthy`：正常路由。
- `degraded`：只接低优先级或少量探测流量。
- `open`：熔断，不再接新流。
- `probe`：半开，少量请求验证恢复。

## 6. 数据面模式

### 6.1 Direct-to-Provider

适合：

- ASR 实时音频上传量较大。
- 云厂商支持临时签名 URL 或可暴露给客户端的短期凭证。
- 客户端可集成 QingYin SDK。
- 需要绕开 2Mbps ECS 带宽瓶颈。

流程：

```text
Client -> QingYin: POST /v1/sessions
QingYin -> Router: 选择 Provider
QingYin -> Adapter: 生成短期 signed connect info
QingYin -> Client: 返回 direct endpoint + provider_session_token
Client -> Provider: 直接推音频
Client SDK -> 统一解析事件或回传结果给业务
QingYin <- Client/Provider: 上报 session metrics
```

优点：

- 不占 QingYin ECS 音频带宽。
- 单台 2C8G2M 可以管理更多会话。
- 云厂商并发能力可直接利用。

缺点：

- 客户端 SDK 要隐藏厂商差异。
- 部分厂商不适合暴露直连凭证。
- 服务端无法逐帧审计音频。
- 切换 Provider 时客户端连接要重建。

适用结论：

这是 2Mbps ECS 的默认推荐模式，尤其适合 ASR。

### 6.2 QingYin Relay

适合：

- 业务不希望客户端感知任何厂商。
- 需要服务端统一事件、审计、风控。
- 音频码率低，且并发不高。
- 本地小模型参与实时决策。

流程：

```text
Client -> QingYin: WS /v1/asr/stream
QingYin -> Provider: 建立厂商 WS/HTTP stream
QingYin: 转发压缩音频，不解码或少解码
QingYin: 归一化 Provider event
QingYin -> Client: QingYin event
```

要求：

- 外部音频必须是 Opus/MP3/AAC 这类压缩格式。
- 如果 Provider 支持 Opus，就直接透传 Opus。
- 不要在 2C ECS 上做大规模实时转码。
- 不允许默认 PCM/WAV。

优点：

- 客户端最简单。
- 统一协议最好。
- 便于切换和降级。

缺点：

- 占用 ECS 出入带宽。
- 同一份音频可能产生双向流量。
- 2Mbps 下活跃流数量有限。

适用结论：

作为兼容模式和低并发模式，不作为大规模默认模式。

### 6.3 Edge Relay

适合：

- 需要统一协议，但中心 ECS 带宽太小。
- 有多个地域用户。
- 需要把音频流量放到带宽更充足的节点。

流程：

```text
Client -> QingYin Control Plane: 创建会话
QingYin -> Client: 分配 edge_relay_url
Client -> Edge Relay: 音频流
Edge Relay -> Provider/Local Worker: 转发或推理
Edge Relay -> Client: 结果/音频
QingYin <- Edge Relay: metrics/audit
```

优点：

- 中心 ECS 只做控制面。
- 可按地域和带宽扩展。
- 不破坏统一协议。

缺点：

- 多一个服务部署单元。
- 要做 Relay 注册、健康检查和路由。

适用结论：

如果后续真实流量上来，这是比堆大中心 ECS 更合理的扩展路径。

### 6.4 Local Inference

适合：

- 隐私要求高。
- 云服务失败或限流。
- 高频短命令。
- 可缓存 TTS。
- 成本敏感场景。

流程：

```text
Client -> QingYin
QingYin -> Local Provider
Local Provider -> sherpa-onnx / SenseVoice / MeloTTS / Kokoro / Piper
QingYin -> Client
```

2C8G 上建议：

```text
max_local_asr_active = 1-2 起步
max_local_tts_active = 1 起步
local_queue_timeout = 50-100ms
overflow = route_to_cloud 或 busy
```

## 7. 带宽策略

### 7.1 默认策略

```text
公网输入：Opus 优先
公网输出：Opus/MP3 优先
内部模型输入：PCM 16k mono
缓存音频：Opus/MP3
禁止默认 base64 音频
禁止默认 WAV/PCM 公网传输
```

腾讯云实时 ASR 文档支持多种音频格式，包括 `pcm、wav、opus、speex、silk、mp3、m4a、aac`，并建议按实时率发送音频片段；腾讯云实时 TTS 文档显示默认可返回 Opus 分片，且 PCM 数据量约为 Opus 的 10 倍。因此聚合层应优先保留压缩编码，不做无意义转码。

### 7.2 数据面选择规则

```text
如果 provider 支持 direct_client:
  优先 Direct-to-Provider

否则如果 provider 支持输入压缩格式且请求量低:
  使用 QingYin Relay

否则如果需要统一中转且流量较高:
  使用 Edge Relay

否则:
  本地小模型或返回 busy / unsupported_codec
```

### 7.3 TTS 缓存优先

TTS 数据面优先级：

```text
1. 本地缓存命中 -> QingYin/CDN 直接返回
2. 本地小模型可低成本生成 -> local_tts
3. 云 TTS 生成并写缓存 -> cloud_tts
4. 云 TTS 失败 -> local_tts 降级音色
```

缓存粒度：

- 短句整句缓存。
- 长文本按分段缓存。
- key 包含文本规范化结果、voice、speed、pitch、sample_rate、codec。

## 8. 本地小模型推理通道

### 8.1 接入方式

本地小模型也注册为 Provider：

```text
local_sherpa_asr
local_sensevoice_enhance
local_melo_tts
local_kokoro_tts
local_piper_tts
```

它们和云厂商走同一个接口：

```text
AsrProvider
TtsProvider
ProviderHealth
ProviderMetrics
ProviderQuota
```

### 8.2 进程形态

2C8G 推荐两种：

方案 A：Rust 进程内推理

```text
qingyin-rs
  -> sherpa-onnx Rust API
```

优点：

- 开销最低。
- 部署最简单。
- 延迟最低。

缺点：

- 崩溃隔离弱。
- 模型运行时和网关绑定。

方案 B：本地 Worker 进程

```text
qingyin-rs
  -> Unix domain socket / localhost gRPC
  -> local-asr-worker / local-tts-worker
```

优点：

- 崩溃隔离更好。
- 模型可独立重启。
- Python/ONNX/Rust 混合更容易。

缺点：

- 多一点进程和通信开销。

建议：

- sherpa-onnx 这类 Rust/C API 可先走进程内。
- SenseVoice/MeloTTS 如果仍依赖 Python，走本地 Worker。

### 8.3 调度规则

本地模型适合：

- 短命令 ASR。
- 静音过滤后的低并发 ASR。
- 热门 TTS 文本。
- 云服务熔断时的降级。
- privacy/local_only 请求。

不适合：

- 高噪音复杂 ASR 主路径。
- 大量并发长音频。
- 高质量多情感 TTS 主路径。
- 没有缓存的长文本 TTS 高并发。

### 8.4 降级等级

```text
L0: 云高质量模型
L1: 云普通模型
L2: 本地小模型
L3: TTS 缓存 / 预制音频
L4: busy / retry_after
```

不要在本地小模型满载时继续排队。实时任务超过 100ms 排队就应该切云或拒绝。

## 9. 统一观测

所有 Provider 必须输出同一套指标：

```text
provider_active_sessions
provider_queue_wait_ms
provider_first_token_ms
provider_first_audio_ms
provider_final_ms
provider_audio_in_bytes
provider_audio_out_bytes
provider_error_count
provider_timeout_count
provider_circuit_state
provider_cost_estimated
provider_cache_hit_count
```

带宽必须单独观测：

```text
gateway_public_in_bps
gateway_public_out_bps
provider_upstream_bps
provider_downstream_bps
direct_session_count
relay_session_count
local_session_count
```

## 10. 推荐落地顺序

### Phase 1：统一协议与适配器框架

交付：

- `Provider` trait。
- `CapabilityRegistry`。
- `Router`。
- 腾讯云 ASR/TTS Adapter。
- Local Mock Adapter。
- 指标和日志。

目标：

- 业务调用 QingYin 协议。
- 内部可切 Provider。

### Phase 2：带宽友好数据面

交付：

- Direct-to-Provider Session API。
- QingYin Relay 模式。
- Opus 优先策略。
- TTS 缓存。
- singleflight。

目标：

- 2Mbps ECS 不被音频流量打爆。

### Phase 3：本地小模型接入

交付：

- sherpa-onnx ASR Provider。
- 本地 TTS Provider。
- local_only 路由。
- 云失败自动降级。

目标：

- 形成自建推理支持渠道。

### Phase 4：多厂商聚合

交付：

- Aliyun / Volcengine / Baidu Adapter。
- 成本/质量/延迟策略。
- 熔断与探测。
- 厂商配额管理。

目标：

- 云厂商可替换、可组合、可降级。

## 11. 最终建议

QingYin 聚合层应明确分成两件事：

```text
控制面：统一、强管控、必须经过 QingYin
数据面：灵活、低带宽、能直连就直连
```

本地小模型也不要做成旁路能力，而要作为正式 Provider 纳入路由。这样后续无论是云厂商、Rust 本地模型、Python 模型、ONNX 模型，业务调用都不变，系统只是在内部改变路由。

2C8G2M 的最佳实践是：

```text
QingYin 做聚合控制面
ASR 大流量优先直连云厂商或 Edge Relay
TTS 优先缓存和压缩分发
本地小模型处理低并发、隐私、降级和高频短文本
所有 Provider 统一限流、熔断和观测
```

## 12. 参考资料

- 腾讯云实时语音识别 WebSocket：https://cloud.tencent.com/document/product/1093/48982
- 腾讯云实时语音合成：https://cloud.tencent.com/document/product/1073/34093
- 阿里云实时语音识别：https://help.aliyun.com/zh/isi/developer-reference/real-time-speech-recognition
- sherpa-onnx：https://k2-fsa.github.io/sherpa/onnx/index.html
- sherpa-onnx Rust API：https://k2-fsa.github.io/sherpa/onnx/rust-api/index.html
