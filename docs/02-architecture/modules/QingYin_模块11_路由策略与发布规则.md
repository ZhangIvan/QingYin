# QingYin 模块 11：路由策略与发布规则

版本：v0.2
目标：让 Provider 选择既可灵活优化质量、延迟和成本，又永远不能绕过隐私、安全、容量和准入约束。

## 1. 决策顺序

一次路由必须按固定阶段执行，后阶段不能推翻前阶段的硬约束：

```text
认证与租户边界
  -> 数据策略/地域/能力硬过滤
  -> Provider 准入和健康过滤
  -> 容量与配额过滤
  -> 数据面可行性过滤
  -> 策略评分与候选排序
  -> 会话 lease 与可观测决策记录
```

因此 `quality_first` 也不能选择未经启用的 Provider，`cost_first` 也不能把 `local_only` 请求发送到云端，`latency_first` 也不能超过环境容量卡中的 Relay 预算。

## 2. 策略层级与合并

策略按从低到高的优先级合并：

```text
platform default
  < region/environment policy
  < organization policy
  < project policy
  < API key/service account restriction
  < per-session request preference
```

高优先级只能收紧低优先级的安全、地域、Provider allow-list、最大时长和额度，不能扩大它们。会话请求中的 `profile` 只是偏好；`local_only`、合规地域、禁用 Provider 和租户上限都是不可覆盖的限制。

| 属性 | 可由会话偏好调整 | 必须由上层批准 |
| --- | --- | --- |
| 质量/延迟/成本权重 | 是，限于已允许范围 | 超出组织策略 |
| Provider 排序 | 是，限于 allow-list | 新增或启用 Provider |
| 数据面优先级 | 是，限于安全可用路径 | 允许 Direct/Edge |
| 隐私与地域 | 否，只能更严格 | 放宽 `local_only` 或地域 |
| 配额与并发 | 否，只能更低 | 提高租户/项目额度 |

## 3. 规范策略内容

一个策略版本必须明确以下内容：

| 区域 | 内容 |
| --- | --- |
| 适用范围 | 地域、环境、组织、项目、API key 或测试标签 |
| 任务规则 | ASR、TTS、Realtime 各自允许的 Provider 与特性 |
| 硬过滤 | 数据驻留、语言、codec、音色授权、最小准入状态、地域、Direct 要求 |
| 数据面顺序 | Direct、Relay、Edge、Local 的优先顺序和禁用条件 |
| 评分 | quality、latency、cost、error、locality、cache、gateway_bytes 的权重和归一化方法 |
| 回退 | 建连、utterance、TTS segment、配额和熔断对应的候选规则 |
| 容量 | 引用的容量卡、Provider 快照、并发/字节/队列闸门 |
| 发布 | 灰度范围、开始/结束、观察窗口、自动回滚阈值 |

策略不可包含明文密钥、静态 URL、真实用户文本或不可追溯的厂商私有字段。

## 4. 评分和候选排序

只有通过硬过滤的候选才进入评分。各指标应转换成同向、可比较的区间，再按 profile 加权：

```text
score(provider, request) =
  Wq * quality_score
  + Wl * latency_score
  + Wc * cost_score
  + Wg * gateway_efficiency_score
  + Wh * health_score
  + Wk * cache_or_locality_bonus
```

指标来源必须可追溯：质量来自版本化评测；延迟和错误来自滚动观测；成本来自快照与账单对账；网关效率来自数据面和容量卡。数据缺失时不假装为高分，而是降低置信度、降权或排除。

相同分数的 tie-breaker 固定为：已缓存 -> 同地域 -> 更低配额压力 -> 稳定 Provider ID 排序。固定规则可避免同一输入在无指标变化时随机跳转。

## 5. 回退边界

| 任务/失败阶段 | 可回退边界 | 不允许的行为 |
| --- | --- | --- |
| ASR 尚未发送音频 | 重新选择并建连 | 消耗多个 Provider 配额后不记录 |
| ASR 正在一句话中 | utterance 边界或客户端重连 | 静默重放未知接收状态的音频 |
| TTS 首段未播 | 重建未播放首段 | 输出混合且无标记的音频 |
| TTS 后续段 | 下一个未播放 segment | 替换已播放内容或音色 |
| Local only 满载 | `busy` 或本地排队预算内等待 | 云端回退 |

策略定义的是候选顺序，真正执行回退仍需受 Provider 状态和容量闸门约束。

## 6. 预览、灰度和回滚

策略变更必须先运行 preview：对最近的匿名化路由样本和人工测试请求比较旧/新策略，输出会话分布、Provider 变化、成本差异、容量影响、失去的能力和潜在隐私冲突。

发布步骤：

1. 创建不可变策略版本，完成 schema 与硬约束校验。
2. 在 sandbox 运行 fixture 和 Provider probe 回归。
3. 指定 canary 租户/项目/流量比例与观察窗口。
4. 持续比较 SLO、错误、成本、熔断、容量水位和取消失败率。
5. 达标则扩大范围；任一自动回滚条件触发则恢复上一稳定版本。

自动回滚阈值必须由环境 SLO 和容量卡配置，不在策略文档内写固定数值。策略回滚只影响新会话；已有会话按照当前 lease 完成或 drain。

## 7. 决策记录

每一次会话路由至少记录：策略版本、容量卡 ID、Provider 快照 ID、候选集合、硬过滤原因、归一化分数、最终数据面、lease 结果、回退链路和结束原因。记录中不得包含原始音频、完整转写、明文票据或密钥。

这些记录既用于解释“为什么选这家”，也用于在某 Provider 质量、成本或错误变化后重放和评估策略影响。
