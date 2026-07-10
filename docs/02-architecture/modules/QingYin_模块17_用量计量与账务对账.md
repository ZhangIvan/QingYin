# QingYin 模块 17：用量计量与账务对账

版本：v0.2
目标：将实时使用、Provider 账单和租户额度分开建模，避免估算值直接成为不可修正的最终收费结论。

## 1. 用量事件

每个可计费动作生成 append-only `Usage Event`，使用全局 event ID、来源序列、session ID、租户、Provider 快照和策略版本去重关联。

| 任务 | 最小计量字段 | 初始状态 |
| --- | --- | --- |
| ASR | 音频毫秒、语音毫秒、语言、Provider request ID、数据面 | observed/estimated |
| TTS | 规范化字符、音频毫秒、voice/model、cache hit、Provider request ID | observed/estimated |
| Realtime | 音频入/出、文本/音频模型单位、turn 数、工具使用（如有） | observed/estimated |
| Cache 分发 | 音频字节、对象版本、命中来源 | observed |
| Local 推理 | CPU 秒、模型版本、音频/字符单位 | observed/estimated cost |

事件状态为 `observed -> estimated -> reconciled`，必要时可进入 `corrected` 或 `disputed`。原始事件不覆盖；修正以引用前序 event 的差分事件表示。

## 2. 预算与预留

会话准入前根据策略估算最大可消耗量，创建短期预算预留。预留只保护实时资源和预算，不直接等于最终扣费。会话结束、取消、超时或 Provider 失败后立即释放未使用部分，并根据实际 Usage Event 结算。

预算层级：平台账户 -> Provider 账户 -> Organization -> Workspace -> Project -> Environment -> API Key/Service Account。低层可收紧但不能突破高层硬上限。一个公司可由 Organization 统一付费，也可为每个 Workspace 配置独立预算、成本中心和告警；账务余额不足时 Router 排除对应 Provider 或返回 `quota_exhausted`，不启动无法支付的长会话。

## 3. Provider 对账

对账周期按 Provider 账单延迟确定。每个 Provider Adapter 必须提供：内部 session/usage ID、上游 request/session ID、计费单位、计费时间窗、币种、价格版本和账单获取方式。

```text
internal usage events
  -> aggregate by provider/account/model/region/window
  -> ingest provider bill or usage export
  -> match by provider request ID or bounded time/usage dimensions
  -> classify variance -> create correction/dispute -> update reconciled totals
```

无法一一匹配的 Direct 会话只能在可信 SDK 遥测、服务端 session 摘要和 Provider 汇总账单三者一致性达到阈值后进入 reconciled；否则保持 estimated 并触发审计。

## 4. 差异与修正

| 差异 | 处理 |
| --- | --- |
| Provider 少报或延迟 | 保留 estimated，等待下一账期，禁止提前冲销 |
| Provider 多报 | 创建 dispute，保留证据和账单版本 |
| 本地重复事件 | 使用 event ID + 来源序列去重，保留重复检测记录 |
| 会话重试重复计量 | 以 idempotency/session/Provider request 关联，建立补偿差分 |
| 缓存命中误计云 TTS | cache hit 为独立用量，禁止同时记为云合成 |

任何对租户展示或计费的修正都需保留原因、审批人（如人工）、引用事件和前后余额。估算与已对账金额必须在控制台/API 中明确区分。

## 5. 报告与权限

租户可查看自己的按项目/环境/任务/Provider 类别聚合的用量、预算消耗、估算/已对账状态、异常和导出任务；不能查看其他租户、Provider 主凭证、内部成本系数或受限诊断。运营角色可查看跨租户汇总和对账差异，但修正、退款或额度变更需要审批工作流。

## 6. 验收

- 故障重试、Direct telemetry 重复、Provider 延迟账单和缓存命中不造成重复或静默漏计。
- 预算预留、释放、最终事件和 Provider 对账可从 session 追溯到最终汇总。
- 对账差异、修正、争议和导出均具备审计记录和权限测试。
