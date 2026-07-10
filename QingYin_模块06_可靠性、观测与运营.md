# QingYin 模块 06：可靠性、观测与运营

版本：v0.2

## 1. 隔离与熔断

Provider、租户、数据面和本地 Worker 都有独立 bulkhead。一个 Provider 的慢连接、错误风暴或额度耗尽不得占满全局 tokio task、会话许可或公网带宽。

熔断状态：`healthy`、`degraded`、`open`、`probe`。连续失败和滚动错误率触发 `open`；半开探测只允许小量新会话。已有会话不强制迁移，只按其失败策略处理。

## 2. 指标

必须按 `provider_id`、`task`、`transport_mode`、`region`、`tenant_tier` 聚合，禁止以 `session_id` 作为高基数标签。

| 范围 | 核心指标 |
| --- | --- |
| 会话 | `active_sessions`、`session_duration_ms`、`disconnect_reason_total` |
| ASR | `first_partial_ms`、`final_after_vad_ms`、`rtf`、`partial_revision_total` |
| TTS | `first_audio_ms`、`audio_rtf`、`chunk_gap_ms`、`cache_hit_total` |
| 网络 | `gateway_public_in_bps`、`gateway_public_out_bps`、`frame_drop_total` |
| Provider | `provider_error_total`、`provider_timeout_total`、`provider_active`、`circuit_state` |
| 本地模型 | `worker_rss_bytes`、`worker_cpu`、`queue_wait_ms`、`model_version_info` |
| 成本 | `estimated_cost_total`、`quota_remaining`、`direct_session_total` |

## 3. 日志与追踪

每个入口生成 `trace_id`，并传给 Adapter；日志使用结构化 `tracing` 字段。正常音频帧不逐帧记日志。错误日志要有 canonical code、Provider code（脱敏）、阶段、重试次数、路径、会话状态和耗时。

追踪采样策略：异常 100%，慢会话 100%，正常会话低比例。生产禁止将文本、token、授权 URL 或音频二进制写入 span 属性。

## 4. 告警与运行手册

初始告警：

- Gateway 出方向连续 3 分钟超过 75% 带宽预算。
- 某 Provider 5 分钟错误率超过阈值或 `open` 超过 10 分钟。
- `first_partial_ms` / `first_audio_ms` P95 超过当前 SLO。
- 本地 Worker RSS/CPU 持续超过阈值或队列超时。
- 租户异常占用活跃流或音频字节。

运行手册按症状提供：停止新 Relay、提高 Direct 权重、禁用 local enhancement、降低 partial 频率、切换主 Provider、冻结高成本租户、回滚 Adapter/模型。所有手册动作应可审计，并优先保护已有实时会话。

## 5. 演练

上线前至少演练：Provider DNS/连接失败、429/配额耗尽、单个 Local Worker 崩溃、Gateway 重启、带宽打满、客户端不读音频、重复 cancel、失效 Direct ticket。演练结果进入发布记录，修复项未关闭不得提高路由权重。
