# QingYin 模块 10：环境容量卡与能力发布

版本：v0.2
目标：把模块 07 的公式变成每个环境可填写、可审批、可发布的容量事实表，并生成对内路由与对外服务能力。

## 1. 环境容量卡

每个 `region + environment + deployment_revision` 建立一张容量卡。卡片不是静态配置文件，而是带来源、时间和有效性的运营资产。

### 1.1 基础信息

| 字段 | 示例形式 | 说明 |
| --- | --- | --- |
| 容量卡 ID | `cap.cn-east.prod.r42` | 唯一、可追溯 |
| 生效范围 | 地域、环境、入口域名、租户层级 | 不同地域不能共用结果 |
| 拓扑 | Control、Relay、Edge、Worker 节点数与角色 | 必须标清音频是否经过中心 |
| 版本 | Gateway、Adapter、模型、codec policy、路由策略 | 任一变化触发失效检查 |
| 负责人 | 技术、SRE、产品审批人 | 对承诺负责 |

### 1.2 资源与保护水位

| 资源 | 输入 | 计算值 | 来源 |
| --- | --- | --- | --- |
| Gateway CPU | 核等价、保留水位、每模式 CPU 消耗 | `gateway_C_available` | 基准压测 |
| Worker CPU | 每模型池的核等价、保留水位、CPU 秒/音频秒 | `worker_C_available` | 模型基准 |
| 内存 | 总内存、基础 RSS、模型 RSS、连接/缓冲 P99、cache budget | `memory_budget` | 运行观测 |
| 网络 | 入/出带宽、headroom、控制预留、各流有效码率 | `usable_ingress/egress` | 云规格+抓包 |
| 连接 | FD、LB、TLS、每连接内存、事件循环实测 | `connections_safe` | 压测 |
| 云 Provider | 并发、QPS、余额、地域、健康容量 | `provider_capacity` | 快照+控制台 |

任何输入字段没有来源或超过有效期，容量卡状态为 `stale`，不可用于提高路由上限。

## 2. 流量画像

容量卡必须使用真实或明确假设的流量画像，而不是只测单接口：

| 分量 | 占比 | 峰值活跃量 | 平均时长 | 语音占空比 | 编码/数据面 |
| --- | ---: | ---: | ---: | ---: | --- |
| Direct ASR | `d_asr` | `n_d_asr` | `t_d_asr` | `u_d_asr` | SDK/Provider |
| Relay ASR | `r_asr` | `n_r_asr` | `t_r_asr` | `u_r_asr` | Opus/Relay |
| Relay TTS | `r_tts` | `n_r_tts` | `t_r_tts` | n/a | Opus/MP3 |
| Cache TTS | `c_tts` | `n_c_tts` | `t_c_tts` | n/a | CDN/Gateway |
| Local ASR | `l_asr` | `n_l_asr` | `t_l_asr` | `u_l_asr` | Local Worker |
| Local TTS | `l_tts` | `n_l_tts` | `t_l_tts` | n/a | Local Worker |

所有占比之和应为 1；若业务尚未上线，必须标记为 forecast 并以多个保守/正常/高峰情景分别计算。

## 3. 从公式到路由上限

容量卡依次执行：

1. 计算每个分量的网络、Gateway CPU、Worker CPU、内存、连接和 Provider 闸门。
2. 按流量画像求解混合约束，避免将每类单独最大值相加。
3. 使用并发阶梯压测验证 P95/P99、错误率、断连、取消和队列时延。
4. 取满足全部 SLO 的最高档位，扣除升级/故障余量，得到 `capacity_safe`。
5. 将 `capacity_safe` 拆成可执行额度：租户活跃流、Provider 并发、Relay 字节令牌、Worker 许可、连接数和缓存下发数。

对外不应公布“服务器理论最大值”，而应公布按能力 profile 划分的可服务额度。示例结构：

| Profile | ASR | TTS | 数据面 | 限制表达 |
| --- | --- | --- | --- | --- |
| `realtime_balanced` | partial/final | 标准流式 | Direct 优先，Relay 备用 | 每项目活跃流、时长、codec |
| `privacy_local` | 本地/近实时 | 本地工程流式 | Local only | 模型、语言、较低并发、无云回退 |
| `quality_cloud` | 云高质量 | 云高质量 | Direct/Edge | Provider 允许的语言、音色和额度 |
| `cached_playback` | 不适用 | 命中缓存音频 | CDN/Gateway | 缓存键与授权范围 |

实际数值来自容量卡，Profile 描述则是稳定的产品契约。

## 4. 发布门与扩容决策

| 决策 | 必须证据 |
| --- | --- |
| 增加租户额度 | 当前卡有效、余量足够、Provider 配额可覆盖、告警可观测 |
| 提高 Relay 上限 | 新带宽/编码/CPU 输入、混合压测、过载保护演练 |
| 增加 Local 并发 | 新模型 CPU/RSS/质量报告、Worker 隔离与取消测试 |
| 增加节点 | 单节点安全容量、流量画像、N+1 不等式、地域路由策略 |
| 新增 Provider 权重 | 模块 09 的 `enabled` 报告、成本和降级策略 |
| 对外发布新 Profile | 容量卡、配额、接口文档、支持边界和回滚开关 |

容量卡的失效条件包括：节点规格、带宽、网络路径、Gateway/Worker/模型/Adapter/编码版本、Provider 配额或 API、路由策略、缓存策略、流量画像、SLO 变化。失效后只能维持或下调已有额度，不能扩大承诺。

## 5. 容量报告摘要模板

每次发布至少输出：

```text
环境与版本：
流量画像与情景：
可用资源与保护水位：
Provider 快照与可用配额：
单流测量（有效码率、CPU 秒、RSS、RTF、首包）：
混合压测结果（P50/P95/P99、错误、断流、取消、队列）：
capacity_safe 及其闸门：
N+1 覆盖结论：
路由/限流/告警配置变更：
风险、回滚和下次复测触发条件：
审批记录：
```

这份摘要将供运营控制台、部署审批、对外套餐/配额和事故复盘共同使用。它必须引用容量卡 ID 和 Provider 能力快照 ID，保证数字可以回溯。

## 6. 验收

- 可以针对任意节点规格、带宽、地域、Provider 配额和流量配比生成容量卡。
- 可以明确说明某个能力受哪个闸门限制，而不是笼统说“服务器不够”。
- 可以在节点失效、Provider 降级或流量结构变化后重算并给出下调/扩容动作。
- 对外能力声明只使用已测、未失效的 `capacity_safe`，不使用理论峰值。
