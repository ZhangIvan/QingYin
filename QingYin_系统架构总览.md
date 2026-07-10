# QingYin 系统架构总览

版本：v0.2
日期：2026-07-10

## 1. 系统定位

QingYin 是实时语音的聚合与编排层，而不是某一家云语音 API 的转售代理。它负责统一协议、策略选择、会话安全、成本控制、数据面编排和本地降级；模型推理可以来自云厂商、边缘节点或本地 CPU Worker。

```text
Business App / QingYin SDK / Browser
        |                    ^
        | Canonical API      | Canonical events / audio
        v                    |
  QingYin Control Plane -----+
  - identity / tenant / quota / policy / session lease
  - provider capability and health / audit / metering
        |
        +----------- chooses data plane -----------+
        |                    |                     |
        v                    v                     v
  Direct Provider       QingYin/Edge Relay    Local Provider
  client <-> cloud      client <-> relay      client <-> worker
```

核心分界：控制面所有请求都经过 QingYin；数据面按会话选择最短、安全且不超带宽的路径。任何 Provider 都不直接暴露给业务服务。

## 2. 服务划分

| 服务 | 职责 | 部署原则 |
| --- | --- | --- |
| `qingyin-gateway` | API、认证、会话、协议归一化、Relay、背压 | 每个接入地域至少一个，按连接与 Relay 容量扩展 |
| `qingyin-core` | 类型、错误码、Provider trait、策略接口、配置 schema | 库，不单独部署 |
| `provider-runtime` | Adapter 生命周期、能力与健康上报 | 可内嵌 Gateway 或独立扩展 |
| `local-inference-worker` | CPU 模型加载与推理 | 按模型 CPU、内存和 RTF 容量独立扩展 |
| `edge-relay` | 高带宽地域音频中继 | 当中心节点容量模型不满足音频流量时部署 |
| `control-api` | 租户、密钥、策略、账单、Provider 管理 | 与 Gateway 分离扩展或同进程起步 |
| `console-web` | 运营与开发者控制台 | 设计确认后实现 |

首期不引入 Kafka、RabbitMQ、MySQL、ELK 等常驻重服务。离线回放、审计落盘和统计任务与实时链路隔离；当多实例和持久审计确有需要时再拆分。

## 3. 关键架构原则

- Session 先路由再建流。同一语音会话不能在多个 Provider 间无状态漂移。
- 厂商差异只能存在于 Adapter。Gateway、SDK、前端只认 Canonical Contract。
- 失败切换以 utterance 或 TTS segment 为边界。流中无缝换厂商会造成重复或丢失音频，首版不承诺。
- 本地模型是具有能力、配额、成本和健康状态的正式 Provider，不是旁路脚本。
- 只有 `direct` 模式可绕开中心节点的大音频流；不能安全签发临时凭证的厂商必须走 Relay/Edge。
- 任何实时队列超过 50-100 ms 都应触发切换或快速失败，而不是等待。

## 4. 典型时序

### 4.1 ASR Direct

```text
Client -> Gateway: create session (requirements + tenant token)
Gateway -> Router: filter and score providers
Gateway -> Adapter: create short-lived connect lease
Gateway -> Client SDK: session lease + selected transport
Client SDK -> Cloud Provider: vendor native audio stream
Client SDK -> Business: canonical partial/final events
Client SDK -> Gateway: telemetry, completion, abnormal close
```

Direct 模式只允许受控 SDK 使用；SDK 负责厂商协议和事件归一化。浏览器直连必须使用短时、单会话、单能力、限来源的凭证，禁止下发长期密钥。

### 4.2 ASR Relay/Local

```text
Client -> Gateway: canonical start + compressed audio frames
Gateway -> Provider Adapter / Local Worker: normalized request + frames
Provider -> Gateway: vendor event / local event
Gateway -> Client: canonical event
```

Relay 默认要求公网 Opus；只有开发调试或受信内网允许 PCM。Gateway 为每帧、每会话和每租户同时执行背压。

### 4.3 TTS

```text
Client -> Gateway: text_append/text_commit or POST text
Gateway -> Cache: exact segment hit?
Cache hit -> Client: compressed audio stream
Cache miss -> selected TTS Provider -> Gateway/SDK -> Client
Gateway -> Cache: write only complete, valid segment
```

云原生 TTS 流式直接映射；非原生 TTS 使用文本分段、并行合成、顺序播放和可取消队列提供工程流式体验。

## 5. 部署阶段

| 阶段 | 形态 | 目的 |
| --- | --- | --- |
| POC | 单台 Gateway + Mock/一个云 Provider | 验证契约而不是容量 |
| 初版生产 | Gateway + Local Worker；云流量按策略选择 Direct/Relay | 以容量模型配置硬阈值 |
| 成长 | Control 节点 + Edge Relay + 独立 Local Worker | 将音频流量移出容量不足的控制节点 |
| 规模化 | 多地域 Control/Edge、专用模型节点、托管缓存与观测 | 多租户可用性 |

## 6. 不接受的设计

- 业务服务直接持有各厂商 AK/SK 或 SDK。
- 公网默认传 PCM、WAV、Base64 音频。
- 把实时帧投入通用消息队列等待消费。
- 依赖单一厂商错误码、事件字段或特定音色 ID。
- 用“连接数”推导“同时推理数”。活跃推理、压缩中继、缓存分发必须分别限流。
