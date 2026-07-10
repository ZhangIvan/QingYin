# QingYin 首条 ASR/TTS 纵向交付切片

版本：v0.2
状态：实现准备基线
目标：用最小但完整的路径验证 QingYin 的统一协议、租户隔离、实时准入、Provider 适配、计量、诊断和降级，而非先堆叠厂商数量或前端页面。

## 1. 切片范围

首条切片服务于一个已启用的 `Organization / Workspace / Project / Environment`，支持：

1. 受项目 API 凭证授权的 `POST /v1/sessions` 创建流式 ASR lease。
2. Relay WebSocket ASR：`start -> session.ready -> binary audio -> asr.partial* -> asr.final -> session.completed`。
3. 受项目 API 凭证授权的 `POST /v1/tts/stream`，在首字节前完成准入，随后返回音频字节流或工程流式分段输出。
4. 一个 `MockProvider` 和一个通过模块 09 准入的主云 Provider Adapter；未完成探针的厂商绝不进入默认路由。
5. session、route snapshot、预算预留、usage event、审计 event、L1-L3 诊断快照全链路可查询。
6. 单一环境的多维限流、并发准入、Provider 熔断、retry-after、cancel 与本地/云受限策略。

切片明确不包含：Direct SDK 真实厂商连接、多轮 LLM 编排、L4/L5 原始内容捕获、完整账单出账、前端正式实现和多区域主动-主动。它们不能阻塞基础契约和数据面被验证。

## 2. 实现顺序与模块职责

| 顺序 | 交付单元 | 责任边界 | 必须提供的证据 |
| --- | --- | --- | --- |
| S1 | `qingyin-core` 契约库 | Resource ID、错误、事件 envelope、状态机、Provider trait | JSON fixtures 与状态机单测 |
| S2 | Control State | 租户链、API credential、幂等、session/reservation/route snapshot | 数据隔离和事务测试 |
| S3 | Gateway Admission | 鉴权、配额、容量卡、限流、短期 ticket、标准错误 | 401/403/409/429 与 retry-after 契约测试 |
| S4 | Relay ASR | WebSocket、二进制音频、背压、cancel、规范事件 | 时序测试与慢消费者测试 |
| S5 | TTS Streaming | HTTP byte stream 或规范 WS 增量 TTS、TTFB、cancel、输出 metadata | 首字节/中断/失败后语义测试 |
| S6 | Provider Runtime | MockProvider、一个已准入 Adapter、能力快照、熔断/退避 | Adapter contract suite 与 sandbox 探针报告 |
| S7 | Usage and Diagnostics | Outbox、用量事件、聚合、审计、L1-L3 快照 | 重试幂等与查询授权测试 |
| S8 | Delivery Evidence | 性能基线、故障演练、OpenAPI/AsyncAPI 兼容检查 | 可复现报告和发布批准记录 |

实现阶段保持 Rust 作为 Gateway/Adapter 主语言。任何厂商 SDK 若只提供其它语言，先使用独立的最小 sidecar 或 HTTP 协议适配层封装在 Adapter 后面，不能把 SDK 类型泄漏到核心或公开 API。

## 3. 端到端参考时序

```text
Client -> Gateway: POST /v1/sessions + project credential + idempotency key
Gateway -> Control State: authorize tenant chain / select policy & capability snapshot
Gateway -> Admission: reserve quota + capacity; persist session/route/outbox atomically
Gateway -> Client: 201 SessionLease + short-lived relay ticket
Client -> Relay: WebSocket connect + start
Relay -> Provider Runtime: normalized ASR stream
Provider Runtime -> Relay: normalized partial/final/error
Relay -> Client: canonical session/asr events
Relay -> Control State: terminal session + usage event + release reservation via outbox
Admin API -> Control State: authorized session diagnostic summary
```

TTS 采用同一准入路径。只有在完成鉴权、容量预留和 Provider 可用性确认后才写 HTTP 200 和第一个音频字节；首字节后故障用模块 12 的流结束语义报告并记录诊断，不能伪造完整成功。

## 4. 限流、降级与失败语义

| 情况 | 切片行为 | 验收判断 |
| --- | --- | --- |
| credential 无效、组织/空间冻结 | 创建前拒绝，`auth`/`policy` 错误 | 不产生 session/reservation/upstream 请求 |
| 重复幂等 key | 返回原语义结果 | 不重复预留、建连或计费 |
| 并发、带宽、预算或容量卡限制 | 创建前 `429` 或 `capacity` 错误，给 retry 提示 | 不进入长队列，不挤占已接纳会话 |
| Provider 短时失败 | 在未写首帧/首字节前按路由规则尝试已批准替代项 | 仅一次有界尝试；记录 route snapshot |
| Provider 流中失败 | 发送规范错误并结束，不重放已消费音频 | 会话终态、预留释放和用量事件一致 |
| Provider 熔断 | 从候选集中剔除至半开探测 | 不把压力反复转给已知失败目标 |
| `local_only` | 只允许已验证本地 Worker；满载返回 busy | 永不偷偷上云 |
| 客户端 cancel/断开 | 停止上游、释放资源、记录终态 | 重复 cancel 成功且无泄漏 |

## 5. 测试矩阵与验收门

| 类别 | 最小测试 | 通过标准 |
| --- | --- | --- |
| 契约 | OpenAPI response、AsyncAPI frame、未知字段、错误 JSON、版本 fixture | 字段、错误码、顺序与文档一致；破坏性变更被 CI 拦截 |
| 状态机 | lease、ready、active、draining、completed、cancel、timeout、upstream fail | 无非法逆向状态；每个会话只有一个终态 |
| 租户隔离 | 组织、空间、项目、环境、API Key、cursor、cache、diagnostic | 跨空间请求统一 404 或权限拒绝，不泄漏是否存在 |
| Provider | MockProvider + 一家已准入云厂商 | 同一输入被归一为相同 canonical 语义；Vendor 原生字段不泄漏 |
| 实时性 | ASR partial、TTS TTFB、背压、慢消费者、音频过速 | 目标 P95/P99 以环境容量卡实测值为门槛，不写死为架构承诺 |
| 韧性 | 限流、熔断、网络断开、Provider timeout、cancel | 不排长队、不重复计费、不重放已发音频 |
| 计量/审计 | 重试、outbox 重放、终态结算、管理员查询 | usage 去重；预留最终释放或结算；审计可追溯 |
| 安全 | ticket 过期、credential 轮换、日志脱敏、诊断权限 | 长期密钥/原文不出现在事件、日志和普通诊断中 |

## 6. 性能验证方法

每一种部署规格独立生成容量卡，使用模块 07 的公式：

```text
capacity_safe = min(network, gateway_cpu, worker_cpu, memory,
                    connections, provider_quota, cost_budget, slo_tested)
```

压测按 ASR、TTS、混合会话分别执行：逐级增加并发，记录 CPU、内存、网络、socket、Relay 排队深度、Provider P95、ASR 首 partial、TTS 首字节、错误率与 cancel 泄漏率。安全并发取所有硬约束的最小值，再按 N+1 和预留余量折减。没有实测容量卡时，该环境只能作为开发/验证环境，不能对外声明并发 SLA。

## 7. 切片完成定义

满足以下全部条件，首条切片才算完成：

- 三份协议文件与实现的契约测试、兼容测试均通过。
- 选定主 Provider 的 sandbox 探针、能力快照、配额和故障测试证据齐全；MockProvider 仍在 CI 中常驻。
- Relay ASR 与 TTS 流在限流、cancel、断网、Provider 故障下均产生可解释且不泄密的统一结果。
- 组织/空间/项目/环境的隔离、预算预留、用量去重、审计、L1-L3 诊断通过自动化测试。
- 对目标部署生成并批准容量卡，性能数据来自可复现压测，不使用预估值冒充承诺。
- 运行手册覆盖恢复、熔断、撤销密钥、暂停空间、Provider 下线和数据留存审批。

完成此切片后再扩展第二 Provider、Direct SDK、本地 Worker、Realtime LLM 编排和前端控制台。这样每一次扩展都建立在已验证的统一边界上。
