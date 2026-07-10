# QingYin 模块 23：实时会话诊断与留存

版本：v0.2
目标：为“实时会话调试”提供独立、脱敏、可授权的数据源。诊断页不能通过抓取普通日志或默认保存用户音频实现。

## 1. 诊断数据分级

| 级别 | 内容 | 默认可见性 |
| --- | --- | --- |
| L1 元数据 | 会话状态、时间、应用、codec、transport、版本、延迟、字节、关闭原因 | Workspace Developer/Analyst |
| L2 事件摘要 | ASR/TTS/LLM 事件类型、时间、长度、稳定性、结果哈希、错误分类 | Workspace Developer，内容默认脱敏 |
| L3 路由与资源 | policy/capacity/provider snapshot ID、质量门、容量预留、回退链路 | Workspace Admin/Analyst |
| L4 受限诊断 | 经授权的文本片段、低保真音量包络、网络包统计、Provider 受限诊断 ID | 明确权限、审计和保留期 |
| L5 内容留存 | 原始音频、完整转写、可播放 TTS 段、prompt/tool 参数 | 默认关闭；显式 Workspace 策略、用户同意、加密与审批 |

实时波形默认使用低保真音量/时间包络，不等于可重建音频。没有 L5 留存权限时，不显示历史音频播放或完整文本。

## 2. 诊断快照与订阅

`SessionDiagnosticSnapshot` 聚合 session summary、规范事件、路由决策、Provider/容量/质量快照和 SDK 遥测，最少包含：session ID、Organization/Workspace、task/status/transport、policy/capacity/provider snapshot、quality gate、audio spec、时延/字节、route nodes、事件摘要、网络遥测、脱敏级别、留存状态和 diagnostic ID。

管理面支持查询快照、cursor 读取事件、订阅活跃会话增量、创建诊断导出 operation、请求/撤销受控留存。订阅只允许当前 Workspace 与会话范围；切换 Workspace、权限失效或会话结束立即停止推送。

## 3. 网络、路由与操作

SDK 只上报策略允许的最小遥测：连接状态、codec、上下行有效码率、事件滞后、RTT、jitter、packet loss、buffer 水位、SDK 版本和关闭原因。指标缺失时 UI 显示“不可用”，不补造网络结论。

路由追踪展示 QingYin 节点（Gateway、Direct SDK/Relay/Edge、Provider role、ASR/TTS/LLM stage）；真实 Provider 名称只对有权限角色显示。右侧“运行依据”只展示该会话实际引用的 policy version、capacity card、provider snapshot 和 quality gate。

`结束并保存` 默认只保存 L1-L3 摘要；`收集诊断信息` 创建脱敏 bundle operation；`取消并结束会话` 必须记录 actor、原因、时间与结果。任何留存、导出或 Support break-glass 操作进入不可变审计。

## 4. 验收

- 活跃会话诊断低延迟更新，不阻塞音频路径或 Provider 流。
- 无 L5 策略时无法通过 UI/API/导出恢复原始音频或全文内容。
- 路由、容量、质量和网络指标均可追溯到版本或遥测来源，且跨 Workspace/过期权限不可读取。
