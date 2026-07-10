# QingYin 模块 04：本地推理、模型与 Worker

版本：v0.2

## 1. 目标

本地推理用于 `local_only` 隐私请求、云故障降级、低成本短语音、高频缓存未命中和模型评估。它的承载量由模型 CPU 时间、RTF、内存和延迟目标共同决定，不由某个低配节点定义上限。

## 2. Provider 划分

| Provider | 初始职责 | 进程形态 | 进入默认路由条件 |
| --- | --- | --- | --- |
| `local.vad` | 静音门控 | Rust 进程内 | 必选 |
| `local.sherpa_asr` | 轻量实时/近实时 ASR | Rust 进程内或独立 Worker | RTF、中文质量通过 |
| `local.sensevoice_enhance` | 句末增强、情感、事件 | Python Worker | 不影响 partial 主链路 |
| `local.melo_tts` | 中文工程流式 TTS | Python Worker | 首包和断句通过 |
| `local.kokoro_or_piper_tts` | 极轻量备选 | 独立 Worker | 中文音质、授权通过 |

所有模型版本、许可证、SHA256、量化方式、语言、测试报告必须进入模型清单。不能以“可运行”代替“可上生产”。

## 3. Worker 协议与隔离

推理 Worker 不对公网暴露。Gateway 通过 localhost gRPC 或 Unix domain socket 访问：

```text
Gateway -> Worker: Start / AudioFrame* / Flush / Cancel
Worker  -> Gateway: Ready / Partial* / Final* / Metrics / Error
```

Rust/C API 运行时可在进程内试验，但生产默认优先隔离模型进程：模型崩溃、内存泄漏或第三方依赖异常不应带倒 Gateway。进程内仅适用于通过压测和崩溃恢复验证的轻量组件。

## 4. CPU 调度基线

每个部署环境为 Gateway、音频处理、系统和每类模型保留独立 CPU 预算。初始线程参数可从保守的单线程模型开始：

```text
OMP_NUM_THREADS=1
MKL_NUM_THREADS=1
OPENBLAS_NUM_THREADS=1
ORT_INTRA_OP_NUM_THREADS=1
ORT_INTER_OP_NUM_THREADS=1
max_local_asr_active=derived_from_capacity_model
max_local_tts_active=derived_from_capacity_model
local_queue_timeout_ms=derived_from_latency_slo
```

压测表明 RTF、TTFB、P95/P99、CPU P95、RSS 和断流均通过后，容量模型才可提高每项上限。ASR 可分流到云，但同一 utterance 不在本地与云之间重复实时推理，除非质量采样实验明确打开。

## 5. 流式策略

- 原生流式 ASR：按模型要求输入帧，输出 partial/final。
- 非原生 ASR：VAD + 320-800 ms 滚动窗口 + 稳定前缀 + utterance 最终重识别；最终增强只能在时间窗内产生 `final_update`。
- TTS：第一段 8-30 汉字，后续 40-100 汉字，标点优先；后台并行合成、顺序输出、短 crossfade/静音边界；取消后停止未开始段。

本地 TTS 的“流式”是服务层体验，不宣称底层模型一定逐帧生成。

## 6. 本地优先策略

| 条件 | 行为 |
| --- | --- |
| `local_only` | 本地可用则执行，否则明确 `unsupported`/`busy`，不泄漏到云 |
| 高频 TTS 缓存命中 | 直接分发 |
| 短句、低风险、local health 正常 | 可本地优先 |
| 方言、复杂噪声、行业热词 | 云优先 |
| 云熔断 | 本地降级，受本地容量闸门保护 |
| 本地队列超时 | 按策略切云；禁止继续堆积 |

## 7. 模型上线门槛

每个模型/量化版本至少有：固定语料 CER/WER 或人工质量对比、RTF、首包、内存、长时稳定性、取消成功率、许可证审查和回滚版本。没有这些证据的模型只能处于 `experimental`，不能成为默认 Provider。
