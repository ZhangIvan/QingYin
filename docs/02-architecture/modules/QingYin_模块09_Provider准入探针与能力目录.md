# QingYin 模块 09：Provider 准入探针与能力目录

版本：v0.2
目标：把“某厂商看起来支持某能力”转化为可重复、可审计、可回滚的 QingYin Provider 启用决定。

## 1. 生命周期

```text
candidate -> access_ready -> sandbox_verified -> canary -> enabled
                    |                 |              |
                    +-> rejected      +-> experimental +-> degraded/open -> retired
```

- `candidate`：仅在调研名单，禁止参与路由。
- `access_ready`：账号、地域、合同、密钥托管和测试许可已就绪。
- `sandbox_verified`：通过协议、安全和基础质量探针，只能供内部测试。
- `experimental`：可供明确选择该能力的内部/灰度租户使用，不能成为默认路由。
- `canary`：有受控真实流量，持续采集质量、SLO、成本和错误数据。
- `enabled`：满足默认路由门槛，可以按策略接收生产会话。
- `retired`：停止新会话；已有会话 drain 后下线，保留审计记录。

Provider 的状态、能力快照和启用范围分开管理。例如一个厂商的 ASR 可以 `enabled`，TTS 仍可能是 `candidate`。

## 2. 准入对象与命名

一个准入对象是 `provider_id + task + region + account_scope + api_revision`，而不是厂商品牌。例如：

```text
tencent.asr.realtime.cn.prod.v1
aliyun.asr.realtime.cn.sandbox.v2
minimax.tts.stream.global.prod.v1
local.sherpa_asr.zh-cn.cpu.int8.v3
```

这样同一厂商不同账号、地域、模型版本或协议版本互不污染。账号范围和凭证引用只在安全配置中保存，能力目录中仅引用不可逆 ID。

## 3. 能力快照

每次探针生成一个不可变能力快照，至少包含以下字段：

| 维度 | 必填内容 |
| --- | --- |
| 身份 | provider_id、厂商、任务、API/模型版本、地域、账户范围 ID |
| 协议 | 传输方式、鉴权方式、请求/事件顺序、取消语义、重连限制 |
| 音频 | 输入/输出 codec、容器、采样率、声道、分帧要求、转码需求 |
| 语言与特性 | 语言/方言、partial、标点、时间戳、热词、SSML、音色能力 |
| 数据面 | 可否安全 Direct、Relay 需求、Edge 适配、允许客户端类型 |
| 限制 | 最大会话时长、并发、QPS、文本长度、码率、地域限制 |
| 质量与性能 | 语料版本、CER/WER 或人工评分、P50/P95/P99、RTF/首包/chunk gap |
| 运营 | 错误码映射、健康探针、成本单位、账单延迟、支持联系人、SLA |
| 安全 | 凭证托管位置、短期票据能力、日志限制、数据留存与合规结论 |

能力快照是路由和控制台的唯一事实来源。静态配置声明与快照不一致时，自动降为 `experimental`，不能接收默认流量。

## 4. 标准探针集

| ID | 类别 | 探针 | 通过条件 |
| --- | --- | --- | --- |
| PV-001 | 访问 | 使用托管凭证建立连接 | 凭证不出服务端；失败可映射 canonical auth error |
| PV-002 | 会话 | 发送规范 start / 创建任务 | 按协议进入 ready，记录建连 P95 |
| PV-003 | ASR 流 | 按真实率发送静音、普通中文、噪声与长句音频 | partial/final 语义可映射，结果与时间戳可解析 |
| PV-004 | TTS 流 | 短句、长句、增量文本与取消 | 音频可播放；mark/结束语义可映射；取消不继续出音 |
| PV-005 | 编码 | 对每种候选 codec/容器发起探针 | 实测支持，不依赖文档推断；记录是否需转码 |
| PV-006 | 特性 | 热词、语言、方言、SSML、时间戳等声明能力 | 每项留下输入、输出和限制，不支持则显式标为 false |
| PV-007 | 异常 | 无效参数、损坏帧、超时、断网、重复 finish/cancel | 归一化错误正确；无泄漏、无无限重试 |
| PV-008 | 配额 | 达到沙箱允许的并发/QPS或模拟 429 | 识别 quota；Router 可剔除或降权 |
| PV-009 | 安全 | Direct 票据、来源限制、TTL、撤销和日志检查 | 无长期凭证暴露；票据不可跨会话复用 |
| PV-010 | 成本 | 单位用量与 Provider 请求 ID 对账 | 估算口径可计算且可与账单核对 |
| PV-011 | 稳定性 | 持续会话、并发阶梯、连接重建 | 取得时延/错误曲线，不只记录单次成功 |
| PV-012 | 可移植性 | 用同一 canonical fixture 替换另一个 Provider | 应用侧字段、事件和错误分类不改变 |

探针音频和文本使用可公开、已授权的固定素材。禁止把真实用户音频、生产密钥和完整输出写入测试报告。

## 5. 启用门槛

| 级别 | 必须通过 | 路由范围 |
| --- | --- | --- |
| sandbox_verified | PV-001 至 PV-007 | 内部测试 |
| experimental | 前项 + PV-008、PV-009、PV-010 | 命名灰度租户，显式选用 |
| canary | 前项 + PV-011、PV-012、质量/性能达到对应产品 profile | 小比例可回滚真实流量 |
| enabled | 连续观察窗口内错误、时延、成本和安全全部达标；有主备/降级策略 | 可参与默认路由 |

`enabled` 不是永久状态。任一能力快照过期、账单异常、账号配额变化、API 版本变化或 SLO 连续失守，都必须自动降级为 `degraded` 或 `experimental`。

## 6. 厂商准入计划

| 通道 | 首个准入对象 | 优先验证点 | 当前设计状态 |
| --- | --- | --- | --- |
| 腾讯云 | realtime ASR、realtime TTS | 临时凭证、Opus、事件稳定性、账号并发 | P0 candidate |
| 阿里云/百炼 | realtime ASR、stream TTS | 当前 API 版本、实时编码、鉴权和区域 | P0 candidate |
| 百度智能云 | realtime ASR、stream TTS | WebSocket 帧语义、文本/音频限制、配额 | P0 candidate |
| 讯飞开放平台 | realtime transcription、online TTS | appid/授权隔离、流式取消和方言能力 | P0 candidate |
| MiniMax | stream TTS | 音色授权、流式格式、字幕/mark、成本 | P0 candidate |
| 字节火山引擎 | ASR/TTS | 账号访问、实时协议、签名、地域与配额 | P1 access review |
| 小米 MiMo | ASR/TTS | 企业权限、模型/API 语义、OpenAI 兼容与音频流 | P1 access review |
| 小米小爱 AIVS | device voice channel | 设备协议、OAuth、产品合作边界 | P2 special integration |

这个表不是厂商能力宣称。只有生成对应的能力快照后，条目才能提升状态。

## 7. 准入报告与变更控制

每次准入输出一份报告，包含：快照 ID、探针版本、运行环境、素材版本、原始结果摘要、错误映射、SLO 曲线、成本样本、风险、建议状态、审批人和回滚开关。

以下变化必须重新探针并生成新快照：API/模型/音色版本、地域、账号、鉴权机制、codec、价格/配额、Adapter 版本、重要依赖或数据处理规则。旧快照保留用于审计，但不得覆盖新路由决策。
