# QingYin 模块 15：限流、准入与降级运行规范

版本：v0.2
目标：在容量、Provider 或安全压力下，以确定、可观测、可恢复的方式保护已有实时会话与隐私边界，而不是靠无界排队维持表面可用。

## 1. 多维资源闸门

每个会话至少同时受以下闸门约束，任一不足都不能准入：

| 维度 | Scope | 计量 | 主要保护对象 |
| --- | --- | --- | --- |
| API 请求 | IP、主体、项目 | QPS/突发 | 认证与控制面 |
| 连接 | IP、租户、Gateway | 并发连接、握手速率 | FD、内存、TLS |
| 会话 | 租户、项目、Provider、数据面 | active sessions、时长 | 并发配额与公平性 |
| 音频字节 | 会话、租户、Relay 节点 | 入/出 bps、总字节 | 带宽与转码 |
| 推理 | Worker、模型、租户 | active streams、CPU 秒、队列预算 | RTF、首包、尾延迟 |
| Provider | 账号、模型、地域 | 并发、RPM/TPM/音频分钟、余额 | 上游配额与成本 |
| 成本 | 项目、租户、Provider | 估算/已核对费用 | 预算与滥用 |

闸门参数必须引用模块 09 Provider 快照、模块 10 容量卡、租户策略和模块 11 路由版本。不得在程序中散落固定上限。

## 2. 准入流程

```text
authenticate -> authorize -> validate request -> select policy
  -> reserve tenant/project capacity -> filter Provider/transport
  -> reserve Gateway/Worker/Provider budget -> create lease -> ready
```

资源预留必须有 TTL。建连失败、客户端取消、ticket 过期和 Provider 创建失败均需幂等释放。已在流中的会话不被新请求挤掉，除非发生安全处置或租户明确的终止策略。

对每个可消耗资源使用令牌桶或等价平滑限流；对并发会话使用许可；对成本使用预算预留再异步对账。瞬时允许量、平均允许量、租户权重与突发容量都必须可从策略和容量卡解释。

## 3. 拒绝与重试语义

| 阶段 | 行为 | 客户端信号 |
| --- | --- | --- |
| 鉴权/策略失败 | 不创建会话 | HTTP 401/403 或 `policy_denied` |
| 准入容量不足 | 不创建会话 | HTTP 429 + `Retry-After` 或 `flow.busy` |
| 建连前 Provider 不可用 | 尝试允许的候选；全部失败则拒绝 | `provider_unavailable` / `flow.busy` |
| 流中出现短时压力 | 降低非关键工作或限帧 | `flow.warning` / `session.degraded` |
| 流中不可恢复故障 | 在合法边界终止或重建 | `session.error` + 可行动原因 |

重试采用带抖动的退避并遵守 `Retry-After`；只重试幂等控制操作和“尚未确认上游接收”的建连阶段。已发送实时音频、已产生最终文本或已输出音频的工作绝不隐式重放。

## 4. 分级降级矩阵

降级必须是策略允许、可见、可审计的。任何等级都不得违反 `local_only`、地域、音色授权或数据保留规则。

| 任务 | L0 正常 | L1 轻度压力 | L2 明显压力 | L3 严重压力 |
| --- | --- | --- | --- | --- |
| ASR | 高质量/完整特性 | 降低 partial 频率 | 关闭增强、仅保留稳定 final | 切至允许的备用/本地模型，或 busy |
| TTS | 选定质量/音色 | 优先缓存、缩小预取 | 使用允许的低成本 voice/model 或增大 segment | 仅缓存/备用模型，或 busy |
| Realtime | ASR+LLM+TTS 全双工 | 降低非关键事件和预取 | 暂停 TTS 或切 turn-based | 只保留已允许的单项能力，或 busy |
| Control API | 全功能 | 降低诊断/列表刷新频率 | 只读关键路径保留 | 拒绝非关键管理操作 |

L0-L3 的实际触发条件由环境 SLO、容量卡和 Provider 健康定义。系统不能把“切换低质量模型”伪装为无变化；`session.degraded` 必须说明影响类别但不泄漏内部 Provider 细节。

## 5. 熔断与恢复

每个 Provider/模型/地域/数据面维护独立 `healthy -> degraded -> open -> probe` 状态。熔断判定输入包括滚动错误率、超时率、P95/P99、配额余量、协议错误和成本异常。半开探测仅允许少量新会话，恢复需要连续成功与 SLO 正常。

Provider `open` 不影响其它 Provider；Local Worker 满载不影响 Direct；某租户超额不影响其它租户。错误域隔离是限流与降级的第一原则。

## 6. 观察、操作与验收

必须观测每个闸门的 `allowed/rejected/reserved/released`、队列等待、降级等级、熔断状态、重试、Provider 回退和客户可见错误。告警阈值引用容量卡，异常操作记录策略/容量/Provider 快照 ID。

生产验收至少证明：

1. 任一资源闸门耗尽时，新请求在 SLO 允许时间内得到确定结果，不造成内存/队列无界增长。
2. 单租户、单 Provider、单模型或单数据面的压测不会拖垮其它健康流量。
3. 每个 L1-L3 降级路径在隐私、计费、事件顺序和客户端显示上均可验证。
4. 熔断、半开、恢复、策略回滚和资源释放均有自动化测试与故障演练记录。
5. 容量卡失效或指标异常时，系统只能维持/下调额度，不能继续扩大准入。
