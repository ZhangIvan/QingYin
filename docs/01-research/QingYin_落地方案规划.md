# QingYin 落地方案规划

版本：v0.1
日期：2026-07-09
约束：CPU-only 部署、全链路支持流式、高强度调用、实时性优先

补充文档：`QingYin_技术选型复核与调用方案.md`

容量补充：`QingYin_2核8G低资源高并发设计.md`

Rust/云服务取舍：`QingYin_Rust自建与云服务取舍.md`

聚合网关与本地推理通道：`QingYin_聚合网关与本地推理通道设计.md`

完整模块化设计与实施计划：`QingYin_系统设计目录与实施计划.md`

## 1. 规划结论

QingYin 不应按“普通离线语音 API”设计，而应按“实时音频流服务”设计。核心路线如下：

1. 对外协议全部支持流式：ASR 使用 WebSocket 双向流，TTS 使用 HTTP chunked / WebSocket 音频流，后续实时对话使用统一 duplex WebSocket。
2. 实时路径不走消息队列：网关直接把流绑定到具体 Worker，避免 RabbitMQ/Kafka 造成排队延迟。消息队列只用于离线任务、审计、异步转写和重试任务。
3. CPU 部署优先选择轻量运行时和受控并发：ASR 优先验证 FunASR online CPU runtime / Paraformer streaming / SenseVoice GGUF；TTS 先用 MeloTTS CPU Worker，后续再验证 ONNX 化收益。
4. 模型边界要明确：SenseVoiceSmall 适合 CPU 高速识别、富文本识别、情感和事件信息；真正低延迟在线 ASR 更适合作为 Paraformer streaming / FunASR online 类 Worker。MeloTTS CPU 可实时推理，但需要工程分段实现“流式播放体验”。
5. 高可用靠 Worker 池、背压、限流、会话粘滞、优雅下线和指标闭环，不靠简单横向扩容堆实例。

## 2. 核心能力边界

| 模块 | 推荐内核 | CPU 可行性 | 流式性质 | QingYin 决策 |
| --- | --- | --- | --- | --- |
| 实时 ASR | FunASR online / Paraformer streaming | 可行 | 原生在线分块识别 | 作为实时 ASR 主路径 |
| 增强 ASR | SenseVoiceSmall | 强，可选 GGUF/ONNX/PyTorch | 更适合作为短分片/句末增强，不作为唯一在线流式假设 | 用于最终校正、情感、事件、非实时转写 |
| TTS | MeloTTS | 官方定位 CPU real-time | 非原生逐帧流式，需要服务层分段合成 | 作为中文 TTS 主路径，工程实现流式 |
| VAD | FSMN-VAD / WebRTC VAD | 强 | 原生流式门控 | 必须前置，降低无效推理 |
| 网关 | Go 优先，Python 可用于 POC | 强 | 长连接管理强 | 生产推荐 Go Gateway |

关键修正：

- “对外支持流式”不等于“模型内核都原生流式”。ASR 可以选择原生 streaming 模型；TTS 对外流式主要由文本切分、任务队列、音频 chunk 输出、缓冲控制实现。
- CPU-only 下不采用 vLLM/TensorRT/GPU FP16 作为主设计，避免方案偏离部署约束。

## 3. 目标架构

```text
Client / SDK / Browser
        |
        | WebSocket / HTTP chunked / SSE
        v
Nginx / HAProxy
        |
        v
QingYin Gateway (Go, production)
  - Auth / API key
  - Rate limit / quota
  - Session routing
  - Backpressure
  - Stream protocol adaptation
  - Worker discovery
        |
        | gRPC bidirectional streaming / HTTP internal streaming
        v
Worker Pools
  ├─ ASR Online Worker
  │   ├─ VAD
  │   ├─ Paraformer streaming / FunASR online CPU runtime
  │   └─ partial / final result emitter
  │
  ├─ ASR Enhance Worker
  │   ├─ SenseVoiceSmall
  │   ├─ final correction
  │   ├─ emotion
  │   └─ audio event tags
  │
  └─ TTS Worker
      ├─ text normalization
      ├─ sentence / phrase chunker
      ├─ MeloTTS CPU inference
      ├─ audio queue
      └─ PCM/WAV/Opus chunk emitter

Redis
  - session metadata
  - rate-limit counters
  - short-lived stream state
  - worker leases

Prometheus / Grafana / Loki
  - latency
  - active streams
  - RTF
  - queue wait
  - CPU / RSS
  - error and disconnect reason
```

实时链路原则：

- ASR 与 TTS 的实时请求不进入普通任务队列。
- 每条长连接必须绑定一个 Worker，直到结束、超时或迁移失败。
- Worker 过载时网关直接拒绝或降级，不让实时请求在队列里长时间等待。
- Redis 存状态，不存大音频流。音频流只走连接或临时文件。

## 4. 对外接口规划

### 4.1 ASR 实时流

接口：

```text
WS /v1/asr/stream
```

客户端第一帧：

```json
{
  "type": "start",
  "session_id": "optional-client-session-id",
  "audio": {
    "format": "pcm_s16le",
    "sample_rate": 16000,
    "channels": 1,
    "frame_ms": 40
  },
  "language": "zh",
  "interim_results": true,
  "enable_punctuation": true,
  "enable_emotion": false
}
```

后续帧：

- 二进制音频帧：20 ms 到 100 ms 一帧，默认 40 ms。
- 控制帧：`pause`、`resume`、`flush`、`stop`。

服务端事件：

```json
{
  "type": "partial",
  "session_id": "s_123",
  "utterance_id": "u_1",
  "text": "今天天气",
  "start_ms": 120,
  "end_ms": 920,
  "stable": false
}
```

```json
{
  "type": "final",
  "session_id": "s_123",
  "utterance_id": "u_1",
  "text": "今天天气不错。",
  "start_ms": 120,
  "end_ms": 1280,
  "stable": true,
  "emotion": null,
  "events": []
}
```

必要事件：

- `ready`：模型和会话已绑定。
- `vad`：语音开始/结束。
- `partial`：中间结果。
- `final`：一句话最终结果。
- `error`：可恢复或不可恢复错误。
- `completed`：会话正常结束。

### 4.2 TTS 流式合成

接口一：适合服务端/客户端直接播放音频。

```text
POST /v1/tts/stream
```

请求：

```json
{
  "text": "你好，我是轻音。接下来我会把回答分段合成为音频。",
  "voice": "zh-default",
  "format": "pcm_s16le",
  "sample_rate": 24000,
  "chunking": {
    "mode": "sentence",
    "max_chars": 80,
    "min_chars": 8
  },
  "stream": true
}
```

响应：

- `Content-Type: audio/pcm` 或 `audio/wav`
- HTTP chunked body 持续输出音频字节。
- 响应头返回 `x-qingyin-session-id`、`x-audio-format`、`x-sample-rate`。

接口二：适合浏览器或实时对话，需要同时传 metadata。

```text
WS /v1/tts/stream
```

服务端事件：

- `audio_start`
- `audio_chunk`
- `mark`：文本片段与音频时间戳。
- `audio_end`
- `error`

TTS 流式实现原则：

1. 首包优先：先合成第一个短句或短语，降低 TTFB。
2. 后台续合成：播放第一段时并行合成后续文本。
3. 保持自然度：按标点、停顿词、最大字数切片，避免机械逐字切分。
4. 降低爆音：片段之间做短淡入淡出或静音边界处理。
5. 可取消：客户端断开后立即停止后续合成。

### 4.3 统一实时对话接口

后续阶段提供：

```text
WS /v1/realtime
```

能力：

- 客户端上传麦克风音频。
- 服务端返回 ASR partial/final。
- 可插入 LLM 文本流。
- TTS 边生成边返回音频。

这个接口是最终用户体验层，内部仍然拆成 ASR、LLM、TTS 三段流。

## 5. Worker 设计

### 5.1 Gateway 职责

Gateway 不加载模型，只处理控制面和网络面：

- API key、租户、配额。
- WebSocket 生命周期。
- 根据 Worker 负载分配会话。
- 对每条流维护 `session_id -> worker_id`。
- 实施背压：超过实时容量时返回 429 或 `busy` 事件。
- 对客户端隐藏后端 Worker 重启和扩缩容细节。

生产阶段推荐 Go，原因是长连接、并发、超时控制和内存稳定性更适合放在 Go 层。POC 阶段可以用 FastAPI 直接实现，尽快打通模型和协议。

### 5.2 ASR Online Worker

职责：

- 接收 PCM 帧。
- 做 VAD 和音频缓存。
- 调用 streaming ASR 模型。
- 输出 partial/final。
- 维护每路流的模型 cache。

实现建议：

- 先验证 FunASR online CPU runtime 或 Paraformer streaming。
- 如果只使用 SenseVoiceSmall，则必须定义为“短分片滚动识别 + 句末修正”，不能承诺真在线 partial 稳定性。
- 音频帧建议 40 ms，服务端可聚合到模型所需 chunk。
- 每路流设置最大静音时长、最大会话时长、最大未 flush 缓冲。

### 5.3 ASR Enhance Worker

职责：

- 对一句话结束后的音频片段做 SenseVoiceSmall 增强识别。
- 产出更稳定 final 文本。
- 按需产出 emotion / audio event。

策略：

- 实时 UI 先显示 Online Worker 的 final。
- Enhance Worker 若在可接受窗口内返回更优结果，发送 `final_update` 事件。
- 若延迟超过阈值，丢弃增强结果或只用于日志和训练样本。

### 5.4 TTS Worker

职责：

- 文本规范化。
- 文本分段。
- MeloTTS 推理。
- 音频格式转换。
- 音频 chunk 输出。

分段策略：

- 第一段优先短：8 到 30 个中文字符，命中标点则提前截断。
- 后续段可略长：40 到 100 个中文字符。
- 遇到数字、英文、专有名词时先做 TN，避免模型读法不稳定。
- 对超长文本使用生产者-消费者模式，边切分边合成边输出。

## 6. CPU 部署与性能策略

### 6.1 进程与线程

CPU-only 最大风险是线程过度竞争。默认策略：

- 一个 Worker 进程只加载一份模型。
- 每个模型进程固定线程数。
- 网关和 Redis 预留 CPU，不把全部核心交给推理。
- 按物理核心规划，不按逻辑线程盲目放大。

建议初始公式：

```text
推理可用核心 = 物理核心数 - 网关预留核心 - 系统预留核心
Worker 数 = floor(推理可用核心 / 单 Worker 线程数)
```

初始参数：

```text
单 ASR Worker 线程数：2-4
单 TTS Worker 线程数：2-4
每 Worker 最大实时流：通过压测决定，不写死
实时请求最大排队时间：50-100 ms
```

### 6.2 推理运行时

ASR：

- 优先验证 FunASR online CPU runtime。
- 验证 SenseVoice GGUF/llama.cpp 路径用于 CPU/边缘部署。
- ONNX Runtime 作为通用优化路径，验证 INT8 后再决定是否进入生产。

TTS：

- POC 使用 MeloTTS PyTorch CPU。
- 优化阶段验证 ONNX 导出、量化、音频后处理成本。
- 如果 ONNX 后音质或韵律损失明显，则保留 PyTorch CPU，优先通过进程池和切分策略优化。

### 6.3 批处理原则

实时服务和离线服务分开：

- 实时 ASR：不做大批处理，只允许小窗口 micro-batch。
- 实时 TTS：第一段不等待批处理，优先 TTFB。
- 离线转写/批量合成：可进入队列并使用动态批处理。

### 6.4 降级策略

当 CPU 压力过高：

1. 关闭 ASR Enhance，只保留 Online ASR。
2. TTS 增大文本 chunk，减少调度次数。
3. 降低 partial 发送频率。
4. 对新实时连接返回 429，不拖慢已有连接。
5. 离线任务暂停消费。

## 7. 高可用设计

### 7.1 会话粘滞

流式会话必须粘到同一个 Worker，因为模型 cache、VAD 状态、音频缓冲都在 Worker 内。Gateway 维护映射：

```text
session_id -> worker_id -> connection_id
```

Worker 下线时：

- 停止接收新会话。
- 已有会话 drain 到结束或超时。
- 超过最大 drain 时间后通知客户端重连。

### 7.2 健康检查

Worker readiness 不应只检查端口，而要检查：

- 模型是否加载完成。
- 线程池是否可用。
- 一段 1 秒静音或测试音频能否完成推理。
- 当前 active streams 是否低于阈值。

### 7.3 背压与限流

实时服务必须有明确拒绝策略：

- 租户级并发限制。
- IP 级连接数限制。
- 每连接最大音频上行速率。
- 最大 session 时长。
- Worker 级 `max_active_streams`。
- 超过容量直接拒绝，不无限排队。

### 7.4 可观测性

必须落地的指标：

ASR：

- `asr_first_partial_ms`
- `asr_final_after_speech_end_ms`
- `asr_rtf`
- `asr_partial_revision_count`
- `asr_active_streams`
- `asr_vad_speech_ratio`

TTS：

- `tts_first_audio_ms`
- `tts_audio_rtf`
- `tts_chunk_gap_ms`
- `tts_active_streams`
- `tts_text_chars_per_second`
- `tts_cancel_count`

系统：

- `worker_queue_wait_ms`
- `gateway_active_ws`
- `cpu_percent`
- `rss_mb`
- `event_loop_lag_ms`
- `disconnect_reason_count`

质量：

- ASR：CER/WER、标点准确率、热词命中率。
- TTS：首包延迟、断句自然度、音频断裂率、人工 MOS 抽检。

## 8. 阶段计划

### Phase 0：基准验证

目标：确认 CPU-only 下模型边界。

交付物：

- ASR streaming POC：FunASR online / Paraformer streaming 在 CPU 上跑通。
- SenseVoiceSmall CPU 跑通，验证短音频 final、情感、事件输出。
- MeloTTS CPU 跑通，测首段合成耗时和长文本分段合成耗时。
- 基准脚本：记录 RTF、TTFB、P50/P95/P99。

验收：

- 明确每种 CPU 规格下单 Worker 可承载的实时流数量。
- 明确 SenseVoice 是否只做增强路径。
- 明确 MeloTTS 分段策略是否能连续播放。

### Phase 1：单体流式服务

目标：最快得到可调用服务。

技术：

- FastAPI
- WebSocket ASR
- StreamingResponse / WebSocket TTS
- 单机 CPU Worker

交付物：

- `/v1/asr/stream`
- `/v1/tts/stream`
- `/healthz`
- `/metrics`
- Dockerfile
- 本地压测脚本

验收：

- ASR 能持续接收音频帧并返回 partial/final。
- TTS 能边合成边返回音频。
- 客户端断开后 Worker 能取消推理和清理资源。

### Phase 2：生产化拆分

目标：支撑高并发长连接。

技术：

- Go Gateway
- Python ASR/TTS Worker
- gRPC bidirectional streaming
- Redis
- Prometheus/Grafana
- Docker Compose

交付物：

- Gateway 服务
- ASR Worker 服务
- TTS Worker 服务
- Worker 注册与租约
- 背压与限流
- 会话 drain

验收：

- 多 Worker 横向扩展。
- 单 Worker 下线不影响新会话分配。
- 过载时新连接被快速拒绝，已有连接不被拖垮。

### Phase 3：CPU 优化

目标：降低成本并提高尾延迟稳定性。

任务：

- ASR GGUF/ONNX 路径压测。
- MeloTTS ONNX 可行性验证。
- INT8 量化准确率评估。
- 线程数、进程数、chunk 大小网格搜索。
- Nginx/HAProxy 长连接参数调优。

验收：

- 给出推荐 CPU 规格与每实例容量。
- P95/P99 延迟有稳定压测报告。
- 量化模型通过质量门槛后才进入默认部署。

### Phase 4：高可用发布

目标：生产上线。

任务：

- 灰度发布。
- 监控告警。
- 租户隔离。
- 请求审计。
- 离线任务队列。
- 自动扩缩容。

验收：

- 有容量表。
- 有回滚方案。
- 有压测报告。
- 有故障演练记录。

## 9. 验收指标草案

这些不是最终承诺值，而是第一轮压测目标。最终 SLA 需要结合 CPU 型号、并发目标和音质/准确率要求确认。

| 指标 | 初始目标 |
| --- | --- |
| ASR 首个 partial | P95 < 500 ms |
| ASR 句末 final | P95 < 1000 ms after speech end |
| ASR RTF | < 1.0，越低越好 |
| TTS 首个音频 chunk | P95 < 800 ms |
| TTS chunk 间隔 | P95 < 120 ms |
| 实时请求排队 | P95 < 100 ms |
| Worker 崩溃恢复 | 新会话 10 秒内恢复调度 |
| 客户端取消清理 | 1 秒内释放会话资源 |

## 10. 技术债和风险

1. SenseVoiceSmall 不能被默认描述为唯一真流式 ASR 内核。必须通过实际 streaming API 验证。
2. MeloTTS 的流式是工程流式，不是天然低层流式声码器。分段过短会影响自然度，分段过长会影响首包延迟。
3. CPU-only 下线程数比实例数更关键，错误配置会造成 P99 急剧恶化。
4. WebSocket 长连接会放大资源泄露问题，必须从第一版就做取消、超时、心跳和断连清理。
5. 音频格式转换可能成为隐性热点，必须纳入压测。
6. 量化不一定提升所有模型的真实延迟，必须以端到端测量为准。

## 11. 近期任务清单

优先级 P0：

- 确认目标 CPU 规格：核心数、架构、内存、是否 AVX2/AVX512。
- 确认目标并发：同时在线流数量、峰值 QPS、平均音频时长。
- 确认 SLA：ASR partial、ASR final、TTS first audio、P95/P99。
- 选定 ASR 实时主路径：FunASR online CPU runtime / Paraformer streaming。
- 跑通 MeloTTS CPU 分段合成 demo。

优先级 P1：

- 定义 WebSocket 消息协议。
- 写基准压测脚本。
- 建立 `/metrics` 指标。
- 做 Docker CPU-only 镜像。
- 补充客户端 demo。

优先级 P2：

- Go Gateway。
- Worker 注册发现。
- Redis 限流和会话状态。
- ONNX/GGUF 优化路线。
- K8s 部署模板。

## 12. 参考资料

- SenseVoice: https://github.com/FunAudioLLM/SenseVoice
- FunASR: https://github.com/modelscope/FunASR
- MeloTTS: https://github.com/myshell-ai/MeloTTS
- ONNX Runtime quantization: https://onnxruntime.ai/docs/performance/model-optimizations/quantization.html
- FastAPI StreamingResponse: https://fastapi.tiangolo.com/advanced/custom-response/
- FastAPI WebSockets: https://fastapi.tiangolo.com/advanced/websockets/
