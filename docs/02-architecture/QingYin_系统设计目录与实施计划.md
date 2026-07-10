# QingYin 系统设计目录与实施计划

版本：v0.2
日期：2026-07-10
状态：架构设计基线

导航：[文档总索引](../INDEX.md) -> [架构索引](INDEX.md) -> [模块索引](modules/INDEX.md)

## 1. 本轮目标与边界

QingYin 的第一版生产目标不是自建一个语音模型平台，而是提供一个稳定的统一语音服务层：业务方只面对 QingYin；QingYin 在内部选择云厂商或本地模型；任何选择都不改变业务协议、审计、配额与观测方式。

本设计覆盖：流式 ASR、流式/工程流式 TTS、统一实时会话、多厂商路由、本地 CPU 小模型、可扩展部署、边缘扩展和运营后台。它不覆盖模型训练、音色授权流程、支付系统和视觉前端的实际实现。

不可违反的约束：

- 对业务侧统一为流式协议；模型不原生流式时允许采用近实时或分段工程流式。
- 实时链路不经过 Kafka、RabbitMQ 等排队型消息队列。
- 控制节点与音频节点分离；每个部署规格必须由容量模型推导其 Relay、Local 和 Direct 承载边界，不能预设统一带宽上限。
- 云厂商和本地模型都必须实现同一套 Provider 契约。
- 任何容量数字都必须经目标机型压测确认，文档中的并发仅是初始限额，不是 SLA。

## 2. 文档地图

| 文档 | 决策范围 | 后续可直接进入的实现模块 |
| --- | --- | --- |
| [系统架构总览](QingYin_系统架构总览.md) | 服务边界、部署形态、关键时序、技术基线 | Rust workspace 与服务边界 |
| [模块 01：统一协议与会话](modules/QingYin_模块01_统一协议与会话.md) | 外部 API、规范事件、会话状态机、SDK 行为 | Gateway、SDK、契约测试 |
| [模块 02：Provider 聚合与厂商接入](modules/QingYin_模块02_Provider聚合与厂商接入.md) | Provider trait、能力注册、路由、厂商接入清单 | Provider Runtime、各 Adapter |
| [模块 03：数据面与音频管线](modules/QingYin_模块03_数据面与音频管线.md) | Direct/Relay/Edge、本机带宽、编解码、背压 | Audio Pipeline、Relay |
| [模块 04：本地推理与 Worker](modules/QingYin_模块04_本地推理与Worker.md) | 小模型、Worker、VAD、缓存、CPU 调度 | Local Provider、模型评测 |
| [模块 05：控制面、租户与安全](modules/QingYin_模块05_控制面、租户与安全.md) | 身份、短期凭证、配额、密钥、用量 | Control Plane、Admin API |
| [模块 06：可靠性、观测与运营](modules/QingYin_模块06_可靠性、观测与运营.md) | 熔断、限流、指标、日志、事件与值班 | Observability、SRE Runbook |
| [模块 07-12：容量、路由与规范](modules/INDEX.md) | 容量模型、需求矩阵、Provider 准入、路由、事件词典 | 容量、策略、契约和验收 |
| [模块 13-19：安全、状态与运营](modules/INDEX.md) | OpenAPI、恢复、限流、状态、计量、SDK、管理面 | 控制面、SRE、账务与控制台 |
| [模块 20-24：公开交互与产品能力](modules/INDEX.md) | 时序、质量、空间、诊断、Realtime LLM | SDK、质量、SaaS 和产品体验 |
| [前端设计稿规范](../03-product/QingYin_前端设计稿规范.md) | 前端信息架构、画板、交互状态、验收标准 | 先出设计稿，确认后再编码 |
| [前端详细设计与数据映射](../03-product/QingYin_前端详细设计与数据映射.md) | 已确认控制台的页面、组件、权限、状态与数据契约 | 前端实现和设计验收 |
| [数据模型与 ERD](QingYin_数据模型与ERD.md) | 强一致实体、租户隔离、存储分层、索引与留存 | 数据库迁移、Repository、缓存与安全测试 |
| [管理面资源契约清单](QingYin_管理面资源契约清单.md) | 控制台资源族、API 覆盖、权限与并发写规则 | Admin API 完整化、前端实现准入 |
| [首条 ASR/TTS 纵向交付切片](QingYin_首条ASR_TTS纵向交付切片.md) | 最小完整交付路径、测试矩阵、性能证据和完成定义 | M1/M2 实现拆分与发布验收 |
| [测试验收与发布计划](QingYin_测试验收与发布计划.md) | 测试层级、容量、灰度、验收门槛 | CI、压测、发布流程 |
| [架构复核与决策记录](QingYin_架构复核与决策记录.md) | 已纠正假设、关键 ADR、剩余验证项 | 每个里程碑的设计复核 |
| [设计冻结审阅与实现准入清单](QingYin_设计冻结审阅与实现准入清单.md) | 设计复核结论、纠正项、外部验证门与实现顺序 | 设计冻结、里程碑评审、生产准入 |
| [Control OpenAPI](../../contracts/openapi/qingyin-control-v1.yaml) | 业务控制面正式 OpenAPI 3.1 契约 | Gateway、服务端 SDK、契约测试 |
| [Admin OpenAPI](../../contracts/openapi/qingyin-admin-v1.yaml) | 组织/空间/容量/质量/诊断/运营任务管理面 OpenAPI 3.1 契约 | Admin API、控制台、权限测试 |
| [Streaming AsyncAPI](../../contracts/asyncapi/qingyin-stream-v1.yaml) | ASR、TTS、Realtime 的 WebSocket AsyncAPI 3.x 契约 | Relay、SDK、事件契约测试 |
| [M1 Rust 核心骨架与运行规范](../04-delivery/QingYin_M1_Rust核心骨架与运行规范.md) | Rust workspace、运行时、ticket、状态、配置和 M1 公共行为 | M1 Gateway、Core、State、Admission、MockProvider |
| [M1 契约 Fixture 与 MockProvider 规范](../04-delivery/QingYin_M1_契约Fixture与MockProvider规范.md) | Golden fixture、MockProvider profile、Provider contract suite 与状态测试矩阵 | M1 测试资产、Adapter 准入和 SDK 兼容 |
| [M1 实施 Backlog 与 CI 门禁](../04-delivery/QingYin_M1_实施Backlog与CI门禁.md) | M1 工作包、依赖、CI、测试环境、阶段证据和退出标准 | 后端实施排期、代码审阅和 M1 验收 |
| [工程实施总计划与 GitHub 治理](../04-delivery/QingYin_工程实施总计划与GitHub治理.md) | G0-M6 路线、分支/PR、审阅、GitHub 保护、阶段复盘 | 云端协作、代码实施、合并与发布治理 |

`../01-research/` 中的早期方案与调研继续保留为决策背景；本套 v0.2 文档为后续模块实现的设计基线。若两者冲突，以 v0.2 为准。

## 3. 实施顺序

### M0：设计冻结与厂商准入

交付：统一事件模型、Provider 契约、三份正式 OpenAPI/AsyncAPI 契约、初始能力清单、供应商账号与密钥方案、Provider 准入探针报告、环境容量卡、数据模型与 ERD。

验收：腾讯、阿里、百度、讯飞、MiniMax 各完成一份 API 探针记录；字节和小米的接入资格、协议、价格、临时凭证能力得到书面确认。三份接口契约通过 lint/fixture 校验，数据模型完成租户隔离审阅。未确认的能力不能写入默认路由。

### M1：可测核心骨架

交付：Rust `qingyin-core` 契约库、`qingyin-gateway`、Mock Provider、配置校验、指标骨架、契约测试，以及“首条 ASR/TTS 纵向交付切片”中的准入、计量、诊断最小闭环。

验收：一个 WebSocket ASR 模拟流和一个 WebSocket TTS 模拟流可完成 `ready -> data -> final/completed`；Provider 可热配置启停；错误可归一化。

### M2：首批云厂商与受控数据面

交付：先接一个主 Provider 与一个备用 Provider；`direct`、`relay` 两条路径；短期会话票据；Opus 优先；基线限流与熔断。

验收：业务方不改协议即可切换 Provider；任意部署规格在 Relay 过载时按容量模型自动拒绝或降级为 Direct，不产生长队列。

### M3：本地推理与缓存

交付：`local_sherpa_asr`、本地 TTS Worker、VAD、TTS cache/singleflight、local-only 策略。

验收：云服务故障时可按策略降级；本地模型满载 100 ms 内转云或返回 busy；缓存命中不进入推理。

### M4：多厂商扩展与运营面

交付：其余厂商 Adapter、Provider 控制台 API、租户配额、用量估算、告警和故障演练。

验收：新增厂商只新增 Adapter 与配置，不修改 Gateway 业务逻辑；每个 Provider 有独立限额、健康、成本和错误视图。

### M5：前端设计稿与实现

交付：按 `../03-product/QingYin_前端设计稿规范.md` 产出高保真设计稿与状态稿，待人工确认后再创建前端工程。

验收：设计稿覆盖桌面和移动端关键流程、空载/加载/异常/权限状态；确认的页面才能进入实现。

## 4. 初始技术基线

| 层 | 选择 | 替换边界 |
| --- | --- | --- |
| 公网 Gateway | Rust + axum/tokio/tower | 外部协议与 `qingyin-core` 不变 |
| 内部 RPC | 首期 trait + in-process / localhost；多节点时 tonic gRPC | Provider trait 不变 |
| 配置与状态 | 文件配置起步，Redis 作为多实例可选项 | 不在实时音频路径存音频 |
| 云接入 | 每厂商一个 Adapter | 厂商 SDK 不允许越过 Adapter |
| 本地 ASR | sherpa-onnx 优先验证，SenseVoice 用于增强 | 以 RTF/质量门槛决定 |
| 本地 TTS | 先验证 MeloTTS Worker，再比较 Kokoro/Piper/ONNX | 对外仍是 TTS Provider |
| 指标与追踪 | Prometheus + OpenTelemetry + tracing | 可导出到任意观测后端 |

## 5. 评审节奏

每完成一个里程碑，必须做一次设计复核：

1. 契约是否仍能兼容已有客户端和 Adapter。
2. 新增能力是否绕过了配额、审计、熔断或指标。
3. 是否把音频流量意外引回容量不足的控制节点。
4. 压测指标是否支持上调并发；不支持则降低阈值，不能用排队掩盖。
5. 厂商文档、价格、配额和临时凭证能力是否仍有效。

## 6. 当前需要保留的决策门

- 默认主 Provider 不能靠主观指定，必须以中文 ASR/TTS 质量、P95、成本、地域和临时凭证能力的探针结果选择。
- Xiaomi 分两条线评估：MiMo 通用模型 API 可以作为候选 Provider；小爱 AIVS 只在设备生态合作场景接入，不能假设为通用服务端 ASR/TTS。
- 字节火山引擎在拿到当前账号权限、实时协议和配额后进入实现；未通过验收前仅为候选项。
- 前端先设计后实现。后端 OpenAPI、事件契约、信息架构稳定后才开始高保真稿。
- 容量不以某一台服务器、某一条带宽或某个连接数作为系统上限；统一使用模块 07 的参数化模型与实际压测结果发布每个环境的承载承诺。
