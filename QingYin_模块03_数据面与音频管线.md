# QingYin 模块 03：数据面、带宽与音频管线

版本：v0.2

## 1. 四种数据面

| 模式 | 音频路径 | 默认使用场景 | 节点资源成本 |
| --- | --- | --- | --- |
| `direct_sdk` | SDK 与云 Provider 直连 | 云支持短期凭证的高并发 ASR | 几乎无音频成本 |
| `relay` | Client -> Gateway -> Provider | 兼容、审计、低并发 | 双向流量，严格限额 |
| `edge_relay` | Client -> Edge -> Provider | 高流量或地域化 | 中心只承载控制面 |
| `local` | Client -> Gateway -> local worker | 隐私、缓存、低并发降级 | 受本机 CPU 与下行带宽限制 |

模式由 Router 在 lease 前确定。Provider 不支持安全直连时，`direct_sdk` 不可选；不能因为节省带宽而把长期厂商密钥暴露给客户端。

## 2. 编解码规则

```text
公网 ASR 上行：Ogg/WebM Opus，16 kHz mono，16-24 kbps 优先
公网 TTS 下行：Opus 或 MP3；浏览器按兼容性选择封装
内部模型输入：PCM s16le，16 kHz mono（模型有要求时例外）
缓存：规范化文本 key + 压缩音频对象
```

不支持：公网默认 PCM/WAV、JSON Base64 音频、跨帧无界缓存、在容量不足的 Gateway 上大规模转码。

若 Provider 支持入站 Opus，Relay 直接透传；否则只有在 CPU token 和带宽 token 同时允许时才解码。浏览器无法稳定输出目标容器时，SDK 应优先本地编码或选择支持 WebM Opus 的 Provider。

## 3. 通用容量闸门

Gateway 的 Relay 上限不由固定带宽决定，而由环境配置和实时测量共同决定。容量模型详见 `QingYin_模块07_能力规划与容量模型.md`，其最小形式为：

```text
usable_egress_bps = configured_egress_bps * egress_headroom
relay_egress_bps  = usable_egress_bps - control_plane_reserve_bps
```

其中 `egress_headroom` 由 SLO 与链路波动确定，初始建议 0.70-0.80，之后以压测结果覆盖。每类资源均有独立闸门：Relay 音频字节、Gateway CPU、Worker CPU、内存、文件描述符、Provider 并发与租户配额。

Direct 会话不计入 Gateway 音频预算，但仍计入租户、Provider 和 Gateway 连接预算。任何环境的默认上限都必须由容量报告生成，不能在代码或文档中写死为某台机器的数字。

## 4. 背压与帧处理

```text
ingress -> frame validation -> byte limiter -> jitter buffer -> VAD -> codec path -> provider
```

- 外部帧目标 20-60 ms；太小会放大消息开销，太大会拉高首字延迟。
- 每会话有固定大小 jitter buffer，满时首先拒绝新帧，不允许内存无限增长。
- VAD 产生 `speech`、`silence`、`end_of_utterance`，静音帧不进入本地 ASR；云 Provider 若要求实时率则仍发送最小必要静音/控制帧。
- ASR partial 发送频率限制为 3-5/s，避免网络与 UI 抖动。
- TTS 采用预取队列：播放中的段、正在合成的段、最多 N 个待合成段；N 由内存预算和 TTS 首包 SLO 推导，取消时一并清理。

## 5. 安全直连票据

会话票据需绑定：`tenant_id`、`session_id`、任务类型、选定 Provider、允许 codec、最大字节/时长、过期时间、nonce、客户端公钥或设备标识（可用时）。票据一次使用、短有效期、服务端可撤销；不得包含厂商主密钥。

无法实现受限临时凭证时，改走 Relay/Edge，或禁止该 Provider 的客户端直连。Direct 会话的完成状态由 SDK 回传并与 Provider 侧账单/事件异步核对。

## 6. TTS 缓存

缓存键：`hash(normalized_text + voice_profile + speed + pitch + format + sample_rate + model_version)`。只缓存完整、校验通过、授权允许复用的音频段。多个相同未命中请求通过 singleflight 合成一次；请求取消不应取消仍有其他订阅者的工作。

缓存分发优先级高于本地/云推理，但必须遵守音色授权、租户隔离和文本敏感性策略。
