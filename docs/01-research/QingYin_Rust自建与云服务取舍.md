# QingYin Rust 自建与云服务取舍

版本：v0.1
日期：2026-07-09
问题：纯 Rust 是否能提升 2C8G2M 的并发，以及是否推荐在已有云服务基础上自建

> 定位说明：本文的 2C8G2M 数字只用于低配比较。通用部署容量与扩容决策以 `QingYin_模块07_能力规划与容量模型.md` 的参数和压测结果为准。

## 1. 结论

纯 Rust 值得做，但不要误判它的收益。

Rust 能明显提升：

- 长连接数量。
- 网关层 QPS。
- 内存稳定性。
- P99/P999 尾延迟。
- 音频转发、编解码、限流、背压效率。
- 部署包体积和冷启动。

Rust 不能直接突破：

- 2 Mbps 公网带宽。
- 2 vCPU 的模型推理上限。
- 模型本身的 RTF。
- TTS 音频下行流量。
- ASR/TTS 模型质量问题。

所以，纯 Rust 可以把 QingYin 从“Python POC 服务”提升为“高性能实时语音网关/轻量推理服务”，但不能把 2 核机器变成能承载几十路同时 ASR/TTS 推理的服务器。

推荐策略：

```text
第一阶段：Rust Gateway + 云 ASR/TTS 或 Python/ONNX Worker
第二阶段：Rust Gateway + sherpa-onnx/ONNX Runtime 本地 ASR/TTS
第三阶段：按成本和质量决定哪些流量自建，哪些继续走云服务
```

## 2. 纯 Rust 能把数据拔高多少

### 2.1 原 Python/FastAPI 估算

在 2C8G2M 上，保守估算：

| 类型 | Python/FastAPI 方案 |
| --- | ---: |
| 空闲 WebSocket/HTTP 长连接 | 500-2000 |
| 轻量控制 API | 数百 QPS |
| 压缩音频流转发 | 20-50 路 |
| 实时 ASR 活跃推理 | 1-4 路 |
| 实时 TTS 活跃合成 | 1-2 路 |

### 2.2 Rust Gateway + 仍用 Python 推理

如果只把网关改成 Rust，模型推理仍在 Python：

| 类型 | 估算 |
| --- | ---: |
| 空闲 WebSocket/HTTP 长连接 | 2000-10000 |
| 轻量控制 API | 1000-5000 QPS |
| 压缩音频流转发 | 30-60 路 |
| 实时 ASR 活跃推理 | 基本不变，1-4 路 |
| 实时 TTS 活跃合成 | 基本不变，1-2 路 |

收益主要在连接层和调度层，不在模型推理层。

### 2.3 Rust + sherpa-onnx/ONNX Runtime 本地推理

如果模型也切到 Rust 可调用的轻量运行时，例如 sherpa-onnx Rust API、ONNX Runtime、GGUF/llama.cpp 类路径：

| 类型 | 估算 |
| --- | ---: |
| 空闲 WebSocket/HTTP 长连接 | 2000-10000 |
| 轻量控制 API | 1000-5000 QPS |
| 压缩音频流转发 | 30-60 路 |
| 实时 ASR 活跃推理 | 2-6 路，优秀小模型可尝试 4-8 路 |
| 实时 TTS 活跃合成 | 1-3 路 |
| TTS 缓存音频分发 | 30-60 路 |

这里的提升来自两个地方：

1. 去掉 Python 解释器、GIL、对象分配和事件循环干扰。
2. 使用更轻的推理运行时和更小的模型。

但如果底层还是同一个 ONNX Runtime C/C++ 内核，Rust 只是把服务层 overhead 降低，推理本身不会因为语言变成 Rust 就自动变快很多。

### 2.4 带宽仍是硬上限

2 Mbps 带宽不因 Rust 改变。

如果 TTS 输出 PCM：

```text
16kHz 16bit mono = 256 kbps
24kHz 16bit mono = 384 kbps
```

2 Mbps 下只能安全跑少数几路。

如果输出 Opus：

```text
16-24 kbps + 协议开销
```

才有可能做到几十路音频分发。

所以 Rust 方案也必须默认：

- ASR 上传用 Opus。
- TTS 下行用 Opus/MP3。
- 禁止公网默认 PCM/WAV。
- 禁止 base64 音频。

## 3. 纯 Rust 推荐技术栈

### 3.1 推荐架构

```text
qingyin-rs
  ├─ axum/tokio
  │   ├─ WebSocket ASR
  │   ├─ HTTP chunked / WS TTS
  │   ├─ SSE metadata 可选
  │   └─ health/metrics
  │
  ├─ tower middleware
  │   ├─ auth
  │   ├─ rate limit
  │   ├─ timeout
  │   ├─ backpressure
  │   └─ request tracing
  │
  ├─ audio pipeline
  │   ├─ opus decode/encode
  │   ├─ resample
  │   ├─ VAD
  │   └─ chunk buffer
  │
  ├─ inference
  │   ├─ sherpa-onnx ASR/TTS/VAD
  │   ├─ ONNX Runtime fallback
  │   └─ optional cloud fallback
  │
  └─ cache
      ├─ local LRU
      ├─ singleflight
      └─ optional Redis
```

### 3.2 核心库选择

| 模块 | 推荐 |
| --- | --- |
| HTTP/WebSocket | axum + tokio |
| 中间件 | tower / tower-http |
| gRPC | tonic，只有多服务拆分时需要 |
| 指标 | prometheus 或 opentelemetry |
| 日志 | tracing |
| ASR/TTS 推理 | sherpa-onnx Rust API 优先 |
| 通用 ONNX | ONNX Runtime Rust binding |
| 音频压缩 | Opus，必要时 MP3 |
| 缓存 | moka/local LRU，必要时 Redis |

### 3.3 不建议的“纯 Rust”

不建议从零实现：

- ASR 模型算子。
- TTS 声码器。
- ONNX runtime。
- 音频编解码器。

正确的纯 Rust 是：

```text
Rust 服务框架 + Rust/C API 推理库 + 成熟音频库
```

而不是手写深度学习推理引擎。

## 4. 云服务 vs 自建

### 4.1 现有云服务能力已经很强

云服务已经覆盖：

- 实时 ASR WebSocket。
- 边说边出字。
- 稳态/非稳态识别结果。
- VAD、热词、自学习、行业模型。
- 实时 TTS、HTTP chunk 输出、Opus/PCM/MP3。
- 并发/QPS 叠加包。

例如：

- 阿里云智能语音交互提供一句话识别、实时语音识别、录音文件识别、语音合成、CosyVoice 大模型语音合成等能力。
- 腾讯云实时语音识别使用 WebSocket，对实时音频流同步返回识别结果，并标注默认单账号并发限制为 200 路，可购买提升。
- 腾讯云实时语音合成支持 HTTP chunk 分片返回，默认可返回 Opus，且官方说明 PCM 数据量约为 Opus 的 10 倍。

这说明：如果目标是快速稳定上线，云服务是很强的默认选项。

### 4.2 什么时候推荐云服务

推荐优先使用云服务，如果满足以下情况：

- 还没验证产品需求。
- 日调用量不稳定。
- 并发峰值高但平均使用低。
- 对准确率、方言、热词、行业模型要求高。
- 团队暂时不想维护模型和压测体系。
- 需要快速上线。
- 需要 SLA、可用性和合规能力。

对于 QingYin 当前阶段，如果业务还在探索，我不建议一开始就全量自建推理。

更推荐：

```text
自建 Rust Gateway
  -> 优先调用云 ASR/TTS
  -> 本地缓存 TTS
  -> 本地 VAD/压缩/限流
  -> 后续逐步替换高频场景为本地模型
```

### 4.3 什么时候推荐自建

推荐自建，如果满足以下情况：

- 请求量稳定且足够大，云服务按量成本明显高。
- 语音数据不能出自己的网络或合规域。
- 需要完全控制延迟、协议、缓存和降级。
- 有大量重复 TTS 文本，可以靠缓存极大降低成本。
- 需要离线、边缘、弱网环境运行。
- 需要深度定制模型、音色或私有热词。
- 已经具备模型部署和压测能力。

自建不是为了“省掉所有成本”，而是把成本从云服务账单转成：

- 机器成本。
- 研发成本。
- 模型评测成本。
- 运维成本。
- 可用性风险。

如果这些能力还没准备好，自建会比云服务更贵。

## 5. 推荐混合方案

最适合 QingYin 的路线不是二选一，而是混合：

```text
Client
  -> QingYin Rust Gateway
      ├─ 本地 VAD
      ├─ 本地限流/鉴权
      ├─ 本地 TTS 缓存
      ├─ 本地小模型 ASR/TTS，处理低成本场景
      └─ 云 ASR/TTS fallback，处理高质量和高峰值场景
```

流量策略：

| 场景 | 路由 |
| --- | --- |
| 内测/低量 | 云服务优先 |
| 热门固定 TTS 文本 | 本地缓存 |
| 高频短句 TTS | 本地轻量 TTS |
| 普通实时 ASR | 云服务或本地 streaming ASR，根据成本切换 |
| 高噪音/方言/行业术语 | 云大模型 ASR |
| 云服务失败/限流 | 本地降级模型 |
| 隐私强需求 | 本地模型 |

这样可以避免两种极端：

- 全云：成本和供应商绑定不可控。
- 全自建：早期研发/运维成本太高。

## 6. 在 2C8G2M 上的最终容量建议

如果使用纯 Rust，并启用 Opus、VAD、缓存、背压：

```text
max_ws_connections = 2000-5000 起步，压测后再上调
max_active_asr_local = 2-4 起步，优秀小模型可尝试 6-8
max_active_tts_local = 1-2 起步，轻量 TTS 可尝试 3
max_cloud_asr_proxy = 100-200，受云账号并发和本机带宽影响
max_tts_cached_downstream = 30-60，受 2Mbps 下行影响
```

如果使用云 ASR/TTS 作为主推理：

```text
本机 CPU 不再是主要瓶颈
主要瓶颈变成：
  - 2Mbps 带宽
  - 云服务账号并发限制
  - 网关连接数
  - 客户端音频码率
```

这种情况下，Rust 网关的价值最大：它可以用很低资源管理大量连接，把真正推理交给云或独立 Worker。

## 7. 我的建议

当前阶段不建议直接“全自建纯 Rust 推理系统”。

建议做：

```text
纯 Rust Gateway + 混合推理
```

具体路线：

1. 先用 Rust 实现协议层：ASR WebSocket、TTS chunk/WS、鉴权、限流、VAD、Opus、metrics。
2. 推理层先接云服务，快速获得稳定能力和并发基准。
3. 本地先只做 TTS 缓存、静音过滤、低成本降级。
4. 并行验证 sherpa-onnx Rust ASR/TTS。
5. 等有真实调用量和成本曲线后，再把高频、可缓存、隐私要求高的流量迁到本地模型。

这样做性能不会差，成本更可控，风险也最低。

## 8. 参考资料

- sherpa-onnx: https://k2-fsa.github.io/sherpa/onnx/index.html
- sherpa-onnx Rust API: https://k2-fsa.github.io/sherpa/onnx/rust-api/index.html
- axum WebSocket/streaming body 文档：Context7 / tokio-rs/axum
- 阿里云智能语音交互：https://help.aliyun.com/zh/isi/product-overview/what-is-intelligent-speech-interaction
- 腾讯云实时语音识别 WebSocket：https://cloud.tencent.com/document/product/1093/48982
- 腾讯云语音识别计费概述：https://cloud.tencent.com/document/product/1093/35686
- 腾讯云实时语音合成：https://cloud.tencent.com/document/product/1073/34093
