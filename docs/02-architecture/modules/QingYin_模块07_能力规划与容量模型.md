# QingYin 模块 07：能力规划与容量模型

版本：v0.2
目的：用可测量的资源、流量与 SLO 推导每个环境可对外承诺的能力；不以单台机器、固定带宽或固定并发作为系统上限。

## 1. 输出什么能力

容量报告必须分别输出以下能力，不能用一个“最大并发”混在一起：

| 能力项 | 单位 | 说明 |
| --- | --- | --- |
| 空闲连接 | connections | 已鉴权、已建立但未传输实时音频的 WS/HTTP2 会话 |
| Direct 会话 | active sessions | 音频不经过 QingYin，但占用会话、SDK、Provider 与租户配额 |
| Relay ASR | active streams | 音频经过 Relay 到云 Provider，按上/下行与网关 CPU 限制 |
| Relay TTS | active streams | 云音频经 Relay 下发，主要受下行与播放 SLO 限制 |
| 缓存 TTS 分发 | downstreams | 不消耗模型推理，但消耗出方向带宽和连接 |
| Local ASR | active inference streams | 受模型 CPU 时间、RTF、内存和 Worker 并发限制 |
| Local TTS | active syntheses | 受首包、音频 RTF、CPU、内存和队列限制 |
| 控制 API | QPS | 创建会话、查能力、管理策略等不含大音频的请求 |

对一个策略配置 `p`，最终安全承载量是所有相关闸门的最小值：

```text
capacity_safe(p) = min(
  network(p), gateway_cpu(p), worker_cpu(p), memory(p),
  connections(p), provider_quota(p), cost_budget(p), slo_tested(p)
)
```

其中 `slo_tested` 不是可用资源，而是压测中同时满足 P95/P99、错误率、抖动和取消时延的最高稳定档位。它拥有最终否决权。

## 2. 规划输入

容量计算先填写环境卡，所有值必须记录来源和测量时间：

| 类别 | 输入变量 | 单位 | 获取方式 |
| --- | --- | --- | --- |
| 流量 | 峰值/平均连接、各模式占比、平均会话时长、语音占空比 | count、%、s | 埋点/业务预测 |
| 网络 | 入/出可用带宽、协议开销、保留水位、地域 RTT | bps、%、ms | 云规格+压测 |
| Gateway | CPU 核数、可用 CPU 水位、每连接内存、每帧 CPU 时间、FD 上限 | core、%、B、CPU-s | 基准压测 |
| Worker | 每模型 RSS、每音频秒 CPU 时间、RTF、会话缓存、可用 CPU/内存 | B、CPU-s/s、ratio | 模型基准 |
| Provider | 账号并发、请求率、日/月额度、区域、成功率 | count、QPS、currency | 控制台/探针 |
| SLO | 首 partial、final、首音频、chunk gap、排队、错误率 | ms、% | 产品决策 |

混合场景不得只测平均值。至少拆成 ASR Direct、ASR Relay、TTS Relay、TTS Cache、Local ASR、Local TTS 六个流量分量。

## 3. 网络能力计算

### 3.1 单流有效码率

```text
stream_bps = payload_bps * protocol_overhead_factor + control_bps
```

- `payload_bps` 是选定编码的实测平均码率，不是名义码率。
- `protocol_overhead_factor` 覆盖容器、TLS、WebSocket/HTTP2、重传和分片开销，应由抓包或压测得到。
- `control_bps` 覆盖心跳、事件 JSON、ACK 与少量元数据。

### 3.2 分方向预算

```text
usable_ingress_bps = provisioned_ingress_bps * ingress_headroom - reserved_ingress_bps
usable_egress_bps  = provisioned_egress_bps  * egress_headroom  - reserved_egress_bps

sum(stream_count_i * ingress_bps_i) <= usable_ingress_bps
sum(stream_count_i * egress_bps_i)  <= usable_egress_bps
```

Relay ASR 主要消耗客户端入方向和到 Provider 的出方向；Relay TTS 主要消耗 Provider 入方向和到客户端的出方向；双工会话在两个方向都叠加。Direct 的音频不进入这两个求和式，但控制事件仍进入连接和 CPU 计算。

若某种单一流量的上/下行分别为 `b_in` 和 `b_out`，其网络上限为：

```text
n_network = min(floor(usable_ingress_bps / b_in), floor(usable_egress_bps / b_out))
```

混合流量使用线性约束而不是逐项相加后的最大值。推荐在容量表中按 1 秒时间窗维护 token bucket，令牌量等于 `usable_*_bps * window_seconds`。

### 3.3 演算示例（仅说明方法）

假设某环境出方向为 100 Mbps，保留系数为 0.70；压测得到一条 Opus Relay TTS 流的有效下行是 27.6 kbps：

```text
usable_egress = 100,000 * 0.70 = 70,000 kbps
n_bandwidth_only = floor(70,000 / 27.6) = 2,536
```

这只是网络闸门，不是对外承诺。还必须与 Gateway CPU、连接、Provider 并发、缓存命中率和 SLO 压测取最小值。换成任何带宽或编码参数即可重算。

## 4. CPU 与推理能力计算

RTF 只描述墙钟速度，不足以直接计算多并发 CPU 占用。必须同时测量每音频秒实际消耗的 CPU 秒：

```text
cpu_core_equivalent_i = process_cpu_seconds_i / audio_seconds_i
```

对可用 CPU 为 `C_available`（已扣除系统、Gateway、编解码和保留水位）的本地模型池：

```text
sum(active_streams_i * speech_duty_cycle_i * cpu_core_equivalent_i) <= C_available
n_cpu_single_type = floor(C_available / (duty_cycle * cpu_core_equivalent))
```

`speech_duty_cycle` 仅在 VAD 确实让静音不入模型时才可小于 1。云 ASR 仍要求实时率发送静音帧时，网络预算不能使用该折减。若模型使用多线程，`process_cpu_seconds` 会自然反映真实核心消耗；不要用线程数猜测容量。

Gateway CPU 使用同一方法：测量每活跃流的 `gateway_cpu_seconds / wall_seconds`，并把 Direct、Relay、Local 分别建模。最终网关能力由总和不超过 `gateway_C_available` 推导。

## 5. 内存、连接与队列计算

```text
memory_required = memory_base
                + sum(worker_replicas_j * model_rss_j)
                + active_sessions * session_state_bytes_p99
                + buffered_audio_bytes_p99
                + cache_budget_bytes

memory_required <= provisioned_memory * memory_headroom

connections_safe = min(
  floor((memory_budget - fixed_memory) / bytes_per_idle_connection_p99),
  file_descriptor_limit - fd_reserve,
  load_tested_event_loop_capacity
)
```

实时队列的上限由时延目标而不是“能存多少任务”确定。对某类任务：

```text
queue_wait_p95 + service_time_p95 <= latency_budget_p95
```

当预测排队时间超过剩余时延预算，准入器必须路由到其他 Provider、降级或 `busy`。这也是所有实时服务不允许无界队列的原因。

## 6. Provider、成本与多节点

```text
provider_capacity_i = min(account_concurrency_i, rate_limit_i, remaining_quota_i, healthy_capacity_i)

tenant_capacity_t = min(tenant_active_limit_t, tenant_byte_limit_t, tenant_cost_budget_t)
```

某 Provider 可承接的流量必须同时满足它自己的能力和 QingYin 节点能力。多节点总容量不是简单乘法：

```text
cluster_capacity = sum(healthy_node_capacity_k) * routing_efficiency
```

`routing_efficiency` 反映地域、会话粘滞、负载不均和升级 drain，初始可通过压测估算。需要容忍一台节点故障时，应满足：

```text
sum(healthy_node_capacity_k) - max(node_capacity_k) >= peak_required_capacity
```

扩容所需节点数基于已测单节点安全容量 `C_node` 和峰值 `P_peak`：

```text
nodes_for_n_plus_one = ceil(P_peak / C_node) + 1
```

当节点规格不同时，直接使用前一条“减去最大节点后仍覆盖峰值”的不等式。

## 7. 容量发布流程

1. 录入环境卡与流量配比，生成理论闸门。
2. 先跑单流基准，得到有效码率、CPU 秒、RSS、RTF 和 SLO。
3. 按真实流量配比逐级加压，记录首次 SLO 失守点。
4. 取失守前一级并减去 HA/发布余量，形成 `capacity_safe`。
5. 将结果写入 Provider 配额、Gateway/Worker admission control、告警阈值和对外套餐说明。
6. 模型、编码、地域、厂商配额或节点规格变化后重新执行。

容量报告的有效期由变更触发，而不是固定日期；任何影响 `stream_bps`、`cpu_core_equivalent` 或 `provider_capacity` 的变化都会使报告过期。
