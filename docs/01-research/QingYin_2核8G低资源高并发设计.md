# QingYin 2核8G低资源高并发设计

版本：v0.1
日期：2026-07-09
机器规格：2 vCPU / 8 GB RAM / 2 Mbps 公网带宽
目标：资源占用低，同时尽可能承受高并发调用

> 定位说明：本文是特定低配节点的历史基准样例，不是 QingYin 的系统能力上限或生产默认配置。后续部署规格、并发和限流统一依据 `QingYin_模块07_能力规划与容量模型.md` 计算并实测确认。

## 1. 直接结论

在 2 核 8G、2 Mbps 带宽的单台 ECS 上，不能把“高并发”理解为“很多路同时做 ASR/TTS 推理”。这台机器可以承受较多连接，但真正昂贵的是：

1. 实时 ASR/TTS 的 CPU 推理。
2. TTS 音频下行带宽。
3. 原始 PCM/WAV 音频流量。

建议目标分层：

| 并发类型 | 可达到量级 | 说明 |
| --- | ---: | --- |
| 空闲 WebSocket / HTTP keep-alive 连接 | 数百到数千 | 用 Go 网关可做到，业务价值取决于活跃比例 |
| 轻量控制 API | 数百 QPS 级 | 不含模型推理、不传大音频 |
| 原始 PCM 实时音频流 | 3-6 路 | 主要受 2 Mbps 带宽限制 |
| 压缩音频流 Opus/MP3 | 20-50 路 | 主要看编码码率和是否同时下行 |
| 实时 ASR 活跃推理 | 1-4 路 | 主要看模型 RTF、VAD 命中率和线程配置 |
| 实时 TTS 活跃合成 | 1-2 路 | 2 vCPU 上建议严格排队和限流 |
| TTS 缓存音频分发 | 20-50 路 | 取决于压缩码率和 2 Mbps 下行 |

如果目标是“几十到几百路同时说话/合成的真实实时语音并发”，单台 2C8G2M 不现实。应该把这台 ECS 定位为轻量网关、调度器、低并发 Worker 或 demo 节点。

## 2. 带宽估算

2 Mbps 理论上约等于：

```text
2 Mbps = 250 KB/s
实际可用建议按 70%-80% 估算 = 175-200 KB/s
```

### 2.1 原始音频码率

| 音频格式 | 单路码率 | 2 Mbps 理论并发 | 建议安全并发 |
| --- | ---: | ---: | ---: |
| PCM 16kHz 16bit mono | 256 kbps | 7 路 | 4-5 路 |
| PCM 24kHz 16bit mono | 384 kbps | 5 路 | 3-4 路 |
| PCM 48kHz 16bit mono | 768 kbps | 2 路 | 1-2 路 |
| Opus 16 kbps | 16-25 kbps 含开销 | 60+ 路 | 40-60 路 |
| Opus 24 kbps | 24-40 kbps 含开销 | 40+ 路 | 30-45 路 |
| MP3 48 kbps | 48-65 kbps 含开销 | 30+ 路 | 20-30 路 |

结论：

- 公网不要传 WAV/PCM 作为默认协议。
- ASR 上行优先用 Opus；TTS 下行优先用 Opus 或 MP3。
- PCM 只适合内网、测试或极低并发场景。

注意：

- 部分云厂商的公网带宽主要限制 ECS 出方向。如果 2 Mbps 只限制出站，那么 TTS 下行最受影响；ASR 客户端上传可能不完全受这个 2 Mbps 限制。
- 如果实际网络是上下行都 2 Mbps，则 ASR 原始 PCM 上传同样会成为瓶颈。

## 3. CPU 估算

CPU 并发不能按连接数算，要按 RTF 算。

```text
可用推理核心 = 2 核 * 70% = 1.4 核
活跃推理并发 ≈ floor(可用推理核心 / 单路 RTF)
```

示例：

| 单路 RTF | 估算活跃推理并发 |
| ---: | ---: |
| 0.2 | 7 路 |
| 0.4 | 3 路 |
| 0.7 | 2 路 |
| 1.0 | 1 路 |

但这只是理论值。2 vCPU 还要跑网关、解码、重采样、JSON、日志、心跳、系统进程，所以生产建议：

- ASR 实时活跃推理：先限 1-2 路，再压测放到 3-4 路。
- TTS 实时合成：先限 1 路，压测后最多 2 路。
- 不要开多个重型模型进程抢 2 个核心。

## 4. 推荐低资源架构

单机版本：

```text
Go Gateway
  - WebSocket / HTTP chunked
  - 鉴权
  - 限流
  - 背压
  - 连接管理
  - 音频协议适配

Python / ONNX Worker
  - ASR Worker: 1 个进程，1-2 推理线程
  - TTS Worker: 1 个进程，1-2 推理线程

Redis 可选
  - 如果只做单机，可先用内存限流
  - 多实例或需要租户配额时再上 Redis

Prometheus metrics
  - 必须保留
```

更省资源的版本：

```text
Go 单进程网关 + Worker 子进程
  - 不上 Nginx，直接 Go TLS 或由云 LB/TLS 终结
  - 不上 Kafka/RabbitMQ
  - 不上 MySQL
  - Redis 可选
  - 日志采样
```

2C8G 上不建议同时部署：

- Nginx + Go Gateway + 多个 Python Worker + Redis + MySQL + Kafka + ELK。
- 多个重型 ASR/TTS 模型常驻。
- GPU 相关运行时和无用依赖。

## 5. 必须采用的高并发策略

### 5.1 音频压缩

外部协议：

```text
ASR 输入：Opus/WebM 或 Ogg Opus
TTS 输出：Opus/WebM、Ogg Opus 或 MP3
内部模型输入：解码为 PCM 16kHz mono
```

不要让公网客户端默认传：

```text
PCM 24k / WAV / base64 audio
```

base64 会额外放大约 33% 流量，不适合 2 Mbps。

### 5.2 VAD 前置

必须做两层 VAD：

1. 客户端 VAD：静音时不上传，直接省带宽。
2. 服务端 VAD：静音不进模型，直接省 CPU。

如果用户平均说话占比 30%，VAD 可以把 ASR 推理压力降到接近三分之一。

### 5.3 严格区分连接并发和推理并发

允许：

```text
max_ws_connections = 500-2000
```

但同时限制：

```text
max_active_asr_streams = 1-4
max_active_tts_jobs = 1-2
max_realtime_queue_wait_ms = 50-100
```

超过容量时直接返回：

```json
{
  "type": "busy",
  "retry_after_ms": 500
}
```

不要让实时请求排长队。排队会让服务看起来没崩，但用户体验已经不可用。

### 5.4 TTS 缓存和 singleflight

TTS 是最适合缓存的部分。

缓存 key：

```text
hash(normalized_text + voice + speed + pitch + sample_rate + codec)
```

策略：

- 热门短句直接返回缓存音频。
- 多个用户请求同一句话时，只合成一次，其他请求等待同一个结果。
- 缓存用本地磁盘或内存 LRU，先不引入复杂对象存储。
- 对长文本按分段缓存，而不是整段缓存。

这样可以把“活跃合成并发”变成“音频分发并发”，CPU 压力会低很多。

### 5.5 降低 partial 频率

ASR 不要每帧都发 partial。

建议：

```text
音频帧：20-40 ms
模型推理窗口：320-800 ms
partial 下发频率：最多 3-5 次/秒
final：VAD 句末后下发
```

这样能减少 JSON、WebSocket 消息、前端渲染和网络开销。

### 5.6 Worker 线程控制

所有推理相关环境变量都要显式设置，避免 2 核机器上线程爆炸：

```text
OMP_NUM_THREADS=1
MKL_NUM_THREADS=1
OPENBLAS_NUM_THREADS=1
NUMEXPR_NUM_THREADS=1
ORT_INTRA_OP_NUM_THREADS=1
ORT_INTER_OP_NUM_THREADS=1
```

如果压测显示单路推理太慢，再把单 Worker 线程调到 2，但不要同时开很多 Worker。

## 6. 建议容量配置

### 6.1 保守生产配置

```text
max_ws_connections = 500
max_active_asr_streams = 1
max_active_tts_jobs = 1
max_tts_audio_downstreams = 20
audio_codec = opus_24k 或 mp3_48k
asr_partial_rate = 3/s
queue_timeout = 100 ms
```

适合第一版上线或内测。

### 6.2 压测后可尝试配置

```text
max_ws_connections = 1000-2000
max_active_asr_streams = 2-4
max_active_tts_jobs = 2
max_tts_audio_downstreams = 30-50
audio_codec = opus_16k/24k
asr_partial_rate = 3-5/s
queue_timeout = 50-100 ms
```

前提：

- ASR RTF 足够低。
- TTS 首包稳定。
- CPU P95 低于 75%。
- chunk gap 没有明显抖动。
- 带宽实际利用不超过 80%。

### 6.3 不建议配置

```text
max_active_asr_streams >= 10
max_active_tts_jobs >= 5
公网 PCM/WAV 输出
所有请求都实时合成、不缓存
没有 VAD
实时请求进入长队列
```

这些配置在 2C8G2M 上会造成尾延迟失控。

## 7. 如果必须承受大量并发

如果“并发”指大量在线用户，但同一时刻少数人在说话/合成：

- 单台 2C8G2M 可以做。
- 关键是连接多、活跃少、推理严格限流。

如果“并发”指大量用户同时 ASR/TTS：

- 单台 2C8G2M 不适合。
- 最低成本方案是拆成：

```text
2C8G2M ECS：Gateway / API / 连接管理
多台低配 CPU Worker：ASR/TTS 推理
对象存储/CDN：缓存 TTS 音频分发
```

更进一步：

- TTS 热门内容走 CDN。
- 客户端 VAD + Opus 必须开启。
- 按租户限 active stream，而不是只限请求数。
- Worker 池按 CPU 使用率和 RTF 自动扩缩。

## 8. 第一轮压测目标

必须测这些指标后才能回答“最大并发”的准确值：

```text
asr_rtf
asr_first_partial_ms
asr_final_after_speech_end_ms
tts_first_audio_ms
tts_audio_rtf
tts_chunk_gap_ms
cpu_percent_p95
rss_mb
network_out_mbps
active_streams
busy_count
disconnect_reason
```

压测方法：

1. 先测单路 ASR/TTS，得到 RTF。
2. 再从 1 路、2 路、4 路递增。
3. CPU 超过 75%、P95 明显上升、chunk gap 抖动时停止。
4. 再测 100、500、1000 个空闲连接。
5. 最后测“多连接、少活跃”的真实场景。

## 9. 最终建议

2C8G2M 的 QingYin 应按这个原则设计：

```text
连接可以多
推理必须少
音频必须压缩
静音必须丢弃
TTS 必须缓存
过载必须拒绝
实时请求不能排长队
```

这个设计下，它可以成为一个非常省资源的实时语音节点；但它不是一台能承载大量同时推理的语音计算服务器。
