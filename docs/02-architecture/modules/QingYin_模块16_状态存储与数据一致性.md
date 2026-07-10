# QingYin 模块 16：状态存储与数据一致性

版本：v0.2
目标：明确每类状态的唯一事实来源、保留期、并发一致性和故障恢复语义。实时音频不进入持久化控制状态。

## 1. 存储分层

生产基线采用“关系型耐久状态 + 高速短期状态 + 受控对象存储”的分层；具体产品可替换，但必须满足对应语义。

| 层 | 适用数据 | 必需能力 | 不适用数据 |
| --- | --- | --- | --- |
| Durable Control Store | 组织、项目、策略、Provider 快照、容量卡、租户配额定义、审计索引、账务汇总 | 事务、约束、版本、备份、跨故障域复制 | 实时音频帧、无界会话缓冲 |
| Ephemeral State Store | session lease、幂等窗口、令牌桶、实时配额预留、短期路由状态 | 原子增减、TTL、快速故障切换 | 永久审计、最终账单 |
| Object Store | 经授权的 TTS cache、审计导出、备份、受控测试素材 | 加密、版本、生命周期、访问日志 | 默认用户音频、密钥 |
| Observability Store | 指标、trace、脱敏日志 | 高写入、保留策略、查询隔离 | 业务状态的唯一事实来源 |

任何生产环境必须为 Durable Control Store 和 Ephemeral State Store 分别定义高可用、备份、恢复与权限策略。所有可隔离实体和索引必须包含 `organization_id` 与 `workspace_id`，缓存、令牌桶、幂等记录和对象路径同样使用该双重前缀。开发/POC 可简化部署，但不能据此宣称生产一致性。

## 2. 核心实体与所有权

| 实体 | 唯一事实来源 | 关键字段/版本 | 生命周期 |
| --- | --- | --- | --- |
| Organization / Workspace / Project / Environment | Durable | ID、父级、状态、RBAC、数据策略、地域 | 显式归档 |
| API Key metadata / Service Account | Durable + secret reference | scope、状态、最后使用、轮换版本 | 撤销后保留审计 |
| Provider Snapshot | Durable、不可变 | snapshot ID、能力、账户范围、探针版本 | 新快照替代，旧快照可审计 |
| Policy Version / Capacity Card | Durable、不可变 | 版本、审批、有效期、前序版本 | 失效后只读 |
| Session | Durable 摘要 + Ephemeral 活跃态 | session ID、tenant、状态、route、trace | 活跃期后摘要保留 |
| Lease / Reservation | Ephemeral | resource、数量、TTL、owner session | TTL 或幂等释放 |
| Idempotency Record | Ephemeral + Durable 摘要 | key hash、request hash、response ref、expiry | 超过重试窗口清理 |
| Usage Event | Durable append-only | event ID、source sequence、单位、状态 | 按账务保留期 |
| Audit Event | Durable append-only | actor、action、object、before/after hash | 按合规保留期 |

密钥明文、Provider 主凭证和一次性 ticket 永不作为普通业务实体保存；只记录受控 secret reference、哈希或撤销状态。

## 3. 会话与租约一致性

会话创建遵守以下顺序：

```text
validate + idempotency lookup
  -> create short-lived resource reservations atomically
  -> persist session intent and immutable routing decision
  -> issue QingYin short-lived lease/ticket
  -> create provider/local session during data-plane handshake
  -> mark active after session.ready
```

任一步失败必须执行幂等补偿：释放未使用 reservation、将 session 标为 failed、保留诊断摘要。ticket 写入失败也必须补偿已持久化的 reservation/session intent。重试同一 `Idempotency-Key` 且请求摘要一致时返回第一次的可安全结果；摘要不同则明确拒绝。

租约是可过期的，不依赖客户端正常关闭。Gateway/Worker 的心跳只用于续租；失联后由 TTL 回收。TTL 回收不得自动重放音频或重新创建 Provider 会话，只释放资源和写入结束原因。

## 4. 并发、时钟与事件

- 所有客户端可见 ID 使用不可预测的全局唯一 ID；Provider ID 与 QingYin ID 分离。
- 版本化实体使用乐观并发控制。更新策略、容量卡、Provider 状态或配额定义时必须带预期版本；冲突返回可重试的管理面错误。
- 令牌桶、计数器和租约操作必须原子化，避免双重准入或双重释放。
- 时钟使用服务器单调计时处理 TTL/超时；持久事件记录 UTC 时间和序列号。客户端时间仅作显示，不能作安全判定。
- Durable State 变更需要 outbox 记录，供审计、缓存失效、异步对账和通知消费；实时音频路径不等待 outbox 消费。

## 5. 保留、删除与恢复

每类实体有显式 retention：会话摘要、幂等记录、用量、审计、缓存、备份各自独立。删除组织/项目触发可审计的级联清理任务，先撤销密钥与 ticket，再停止新会话、drain 活跃会话、删除受限数据、保留法律/账务所需最小记录。

备份恢复必须验证：策略/容量卡版本不回退到未批准状态；配额和账务不重复扣减；撤销的密钥不重新生效；已过期 ticket 不能复活。恢复后的活跃流按不可迁移原则要求客户端重连。

## 6. 验收

- 并发创建、重复提交、超时、Gateway/Worker 崩溃和 State Store 故障不产生资源泄漏、双重计费或越权会话。
- 所有活动 session 能关联到策略版本、容量卡、Provider 快照和租约；所有结束原因可追溯。
- 备份恢复、TTL 回收、幂等重试、乐观并发和删除流程均有自动化与演练证据。
