# QingYin 技术选型复核与调用方案

版本：v0.1
日期：2026-07-09
核心约束：CPU-only、全链路流式体验、高并发调用、实时优先

## 1. 结论

当前方案的架构方向是对的，但模型选型需要从“固定 SenseVoiceSmall + MeloTTS”调整为“主路径 + 平替路径 + 降级路径”。

推荐主方案：

```text
Go Gateway
  -> ASR Online Worker: FunASR online / Paraformer streaming / sherpa-onnx streaming ASR
  -> ASR Enhance Worker: SenseVoiceSmall
  -> TTS Worker: MeloTTS 分段流式输出
  -> Redis: 会话、限流、租约
  -> Prometheus/Grafana/Loki: 指标、日志、告警
```

这个组合不是理论上最极致的，但它最适合第一阶段落地：模型生态成熟、CPU 可跑、中文能力较好、工程复杂度可控。

如果压测后发现 Python Worker 扛不住，最佳平替不是先上 Rust，而是优先切到：

```text
Go Gateway + sherpa-onnx / ONNX Runtime / FunASR runtime Worker
```

这条路线更符合 CPU-only、高并发、低运维复杂度的目标。

## 2. 当前方案是否最佳

### 2.1 架构层面

当前“Gateway + Worker 池”的架构是最佳方向。

原因：

- 流式服务是长连接密集型，不适合让模型服务直接裸露给外部。
- CPU 推理必须做严格背压，否则 P99 会快速恶化。
- ASR、TTS、增强识别的负载模型不同，必须拆开扩容。
- 实时链路不能经过 Kafka/RabbitMQ 这种排队型消息队列。

需要调整的地方：

- POC 可用 FastAPI 单体，但生产不建议 FastAPI 同时承担公网网关、鉴权、长连接调度和推理。
- 消息队列只用于离线任务、审计、日志回放、失败重试，不进入实时 ASR/TTS 主链路。
- Worker 的容量要按 active stream、RTF、首包延迟来定，不按普通 QPS 来定。

### 2.2 模型层面

SenseVoiceSmall + MeloTTS 不是“唯一最佳”，但可以作为一个很好的起点：

- SenseVoiceSmall：适合 CPU、短音频、高质量 final、情感/事件增强；不应强行定义为唯一在线流式 ASR 内核。
- MeloTTS：适合 CPU 快速 TTS；不是底层原生流式，但可以通过工程分段做出流式播放体验。

更稳的模型策略：

```text
ASR partial/final 实时主路径：FunASR online / Paraformer streaming / sherpa-onnx
ASR 高质量增强路径：SenseVoiceSmall
TTS 低延迟主路径：MeloTTS 分段合成
TTS 高质量平替：CosyVoice streaming，资源足够时启用
TTS 极轻量平替：Piper / Kokoro ONNX / sherpa-onnx TTS，按中文效果压测决定
```

## 3. 方案分级

### 3.1 方案 A：最快落地

```text
FastAPI 单体
  - /v1/asr/stream WebSocket
  - /v1/tts/stream StreamingResponse / WebSocket
  - Python 内直接加载模型
```

适合：

- POC
- 内部 demo
- 单机验证模型效果
- 快速打通调用链

优点：

- 研发速度最快。
- 与模型 Python 生态贴合。
- 调试成本低。

问题：

- 长连接、鉴权、限流、背压和模型推理混在一起。
- 高并发下事件循环和推理线程容易互相影响。
- 横向扩容和优雅下线会比较粗糙。

结论：

可以作为 Phase 1，但不是生产终局。

### 3.2 方案 B：推荐生产方案

```text
Go Gateway
  -> Python ASR Worker
  -> Python TTS Worker
  -> Redis
  -> Prometheus
```

适合：

- 第一版生产。
- 需要快速保留 Python 模型生态。
- 需要支撑较多 WebSocket 长连接。

优点：

- Go 管连接、鉴权、限流、调度和背压。
- Python 只做模型推理。
- Worker 可按模型类型独立扩容。
- 迁移到 ONNX/sherpa-onnx 时不影响外部协议。

问题：

- 多语言工程复杂度高于 FastAPI 单体。
- 内部协议、Worker 注册、会话粘滞需要设计好。

结论：

这是当前 QingYin 的默认推荐。

### 3.3 方案 C：CPU 极致平替

```text
Go/Rust Gateway
  -> sherpa-onnx / ONNX Runtime / FunASR runtime Worker
```

适合：

- CPU-only 压测后发现 Python Worker 成本过高。
- 需要更低内存、更稳定尾延迟。
- 能接受模型格式转换和效果复测。

优点：

- 运行时更轻。
- 线程模型更可控。
- 更适合嵌入式、边缘节点、裸机 CPU 服务。

问题：

- 模型选择和中文效果需要重新压测。
- 预处理、后处理、标点、热词等能力可能不如 Python 生态现成。
- 团队调试门槛更高。

结论：

不是第一天就上，但应该作为 P1 平替路线提前验证。

### 3.4 方案 D：质量优先平替

```text
Go Gateway
  -> CosyVoice streaming TTS Worker
  -> ASR Online Worker
```

适合：

- TTS 自然度优先。
- 并发量没有极端高。
- 可接受更高 CPU 成本。

优点：

- TTS 质量和实时交互潜力更强。
- 支持更复杂音色和表达。

问题：

- CPU-only 高并发成本更高。
- 冷启动、内存、首包延迟需要重点压测。

结论：

适合作为高质量模式或高级租户能力，不建议作为第一阶段唯一 TTS。

## 4. 非原生流式的替代实现

核心判断：只要总推理速度足够快，并且首包延迟可控，就不必死咬“模型底层原生流式”。对用户来说，体验上的流式更重要。

### 4.1 ASR 近实时方案

如果 ASR 模型不能直接稳定 streaming，可以用：

```text
VAD -> 滚动窗口 -> partial guess -> 句末 final -> final_update
```

实现方式：

1. VAD 先判断说话开始和结束。
2. 每 320-800 ms 把最近音频窗口送入模型。
3. partial 只展示稳定前缀，避免频繁改字。
4. 句末静音后，用完整 utterance 再识别一次。
5. SenseVoiceSmall 可作为 final correction。
6. 如果增强结果更好，在 1 秒窗口内发送 `final_update`。

这不是严格原生流式，但如果 RTF 明显小于 1，并且窗口控制得好，用户体验可以接近实时。

适用：

- SenseVoiceSmall 做短分片识别。
- Whisper.cpp 类模型做滑窗识别。
- 在线模型不稳定时的兜底。

风险：

- partial 可能回改。
- 窗口太短会丢上下文，太长会增加延迟。
- 并发高时重复滑窗会增加 CPU 开销。

控制手段：

- 只在用户需要 interim result 时开启 partial。
- partial 发送频率限制在 3-5 次/秒以内。
- 使用 VAD 减少无声片段推理。
- 对相邻窗口做文本前缀稳定算法。

### 4.2 TTS 工程流式方案

MeloTTS 这类非原生 streaming TTS 可以这样做：

```text
文本流输入
  -> 轻量断句器
  -> 第一段短句快速合成
  -> 后续分段后台合成
  -> 音频队列
  -> chunked/WebSocket 输出
  -> 片段间淡入淡出/静音边界处理
```

关键参数：

```text
第一段：8-30 个中文字符
后续段：40-100 个中文字符
首包目标：P95 < 800 ms
片段间 gap：P95 < 120 ms
客户端缓冲：100-300 ms
```

这类方案的本质是“边切分、边合成、边播放”。它不会减少整段文本的总计算量，但能显著降低感知延迟。

适用：

- MeloTTS
- Piper
- Kokoro ONNX
- 其他短句合成速度快的 TTS

风险：

- 断句不好会影响自然度。
- 分段音色和韵律可能不连续。
- LLM 文本流如果频繁回改，TTS 需要可取消。

控制手段：

- 标点优先断句。
- 没标点时按语义词和最大字符数断句。
- 第一段短，后续段稍长。
- 每段加 mark 事件，方便前端同步文本。
- 片段间做短静音或 crossfade。

## 5. 调用链落地

### 5.1 外部调用

ASR：

```text
Client
  -> WS /v1/asr/stream
  -> start JSON
  -> binary PCM frames
  <- ready
  <- partial
  <- final
  <- completed
```

TTS：

```text
Client
  -> POST /v1/tts/stream
  -> JSON text request
  <- HTTP chunked audio bytes
```

或：

```text
Client
  -> WS /v1/tts/stream
  -> text_append / text_commit / cancel
  <- audio_chunk
  <- mark
  <- completed
```

实时对话：

```text
Client
  -> WS /v1/realtime
  -> audio input frames
  <- asr_partial
  <- asr_final
  <- tts_audio_chunk
  <- tts_mark
```

### 5.2 内部调用

Gateway 到 Worker 推荐 gRPC 双向流：

```protobuf
service AsrService {
  rpc Stream(stream AudioFrame) returns (stream AsrEvent);
}

service TtsService {
  rpc Stream(TtsRequest) returns (stream AudioChunk);
}
```

如果第一阶段不想上 gRPC：

- FastAPI Gateway -> Worker HTTP/WebSocket 也能用。
- 但内部协议要保持和 gRPC 可迁移的事件模型。
- 不要把内部调用设计成一次性 REST 阻塞接口，否则后面改流式会返工。

### 5.3 调用完成标准

第一阶段“完成调用”不是只跑通一个 API，而是至少满足：

- 客户端能持续推 PCM。
- 服务端能实时返回 partial/final。
- TTS 能返回可边播的音频 chunk。
- 客户端断开后服务端能停止推理。
- Worker 过载时能快速拒绝新流。
- 所有请求能记录 session_id 和 latency 指标。

## 6. 推荐选型矩阵

| 场景 | 推荐选型 | 说明 |
| --- | --- | --- |
| 最快打通调用 | FastAPI 单体 + Python 模型 | 只用于 POC |
| 第一版生产 | Go Gateway + Python Worker | 综合最稳 |
| CPU 极致性能 | Go/Rust + sherpa-onnx/ONNX Runtime | 需要效果复测 |
| ASR 实时 partial | FunASR online / Paraformer streaming / sherpa-onnx | 不建议强压 SenseVoice 做唯一实时内核 |
| ASR final 增强 | SenseVoiceSmall | 适合补质量和情感/事件 |
| TTS 低延迟 | MeloTTS 分段流式 | 工程流式，性价比高 |
| TTS 高质量 | CosyVoice streaming | CPU 成本更高 |
| TTS 极轻量 | Piper / Kokoro ONNX / sherpa-onnx TTS | 中文效果必须实测 |
| 内部实时通信 | gRPC bidirectional streaming | Worker 间契约清晰 |
| 外部 ASR | WebSocket | 双向音频/事件最自然 |
| 外部 TTS | HTTP chunked 或 WebSocket | 只播音频用 HTTP，需要元数据用 WS |
| 消息队列 | 不进实时链路 | 只做离线、审计、回放 |

## 7. 最终建议

不要把项目卡死在“某个模型是否原生支持流式”上。QingYin 的正确落点是：

```text
协议层必须流式
服务层必须可取消、可背压、可观测
模型层允许原生流式、滑窗近实时、分段合成并存
```

第一阶段建议执行：

1. 用 FastAPI 打通 `/v1/asr/stream` 和 `/v1/tts/stream`。
2. ASR 同时验证 FunASR online/sherpa-onnx 与 SenseVoiceSmall 增强路径。
3. TTS 先做 MeloTTS 分段流式，记录首包和 chunk gap。
4. 一周内用压测结果决定是否保留 Python Worker，还是提前切 sherpa-onnx/ONNX Runtime。
5. 协议从第一天就按生产形态设计，避免 POC 代码绑死成阻塞 REST。

这样做的好处是：用户体验保持流式，CPU 成本可控，模型可以替换，调用协议不会返工。

## 8. 参考资料

- SenseVoice: https://github.com/FunAudioLLM/SenseVoice
- FunASR: https://github.com/modelscope/FunASR
- MeloTTS: https://github.com/myshell-ai/MeloTTS
- CosyVoice: https://github.com/FunAudioLLM/CosyVoice
- sherpa-onnx: https://github.com/k2-fsa/sherpa-onnx
- Piper: https://github.com/rhasspy/piper
- FastAPI WebSockets: https://fastapi.tiangolo.com/advanced/websockets/
- FastAPI StreamingResponse: https://fastapi.tiangolo.com/advanced/custom-response/
- ONNX Runtime quantization: https://onnxruntime.ai/docs/performance/model-optimizations/quantization.html
