# QingYin 模块 18：客户端 SDK 与 Direct 会话规范

版本：v0.2
目标：让应用在 Direct、Relay、Edge 和 Local 数据面下始终使用 QingYin 的统一会话、事件、错误和取消语义，而不是感知厂商 SDK。

## 1. SDK 责任边界

SDK 负责创建/控制 QingYin 会话、采集与编码、规范事件分发、Direct 协议桥接、心跳、取消、受控重连和最小遥测。SDK 不保存 Provider 主凭证、不暴露 Provider 私有事件、不绕过 QingYin 的策略/配额，也不替业务持久化原始音频或转写。

SDK 形态可以是 Web、Mobile、Server，但每种形态都必须实现同一会话接口。浏览器 SDK 不接收长期项目 API Key；它从业务后端获得 QingYin 一次性 session ticket。

## 2. 数据面行为

| 模式 | SDK 行为 | 不变量 |
| --- | --- | --- |
| Direct | 使用 ticket 建立允许的 Provider 会话，内部映射事件并回传最小遥测 | 应用只收 QingYin event；不泄漏长期 Provider 密钥 |
| Relay | 连接 QingYin WS/HTTP，发送规范控制帧和协商音频 | Gateway 保留流控与审计边界 |
| Edge | 先从 QingYin 获得受控 Edge 地址，再使用相同规范流 | 中心控制面仍持有策略与租约 |
| Local | 与 QingYin Gateway/本地受控入口通信 | `local_only` 不建立云连接 |

数据面由 `session.ready` 明示为规范 `transport_mode`，不向普通业务代码暴露真实 Provider ID。调试模式可在授权后展示受限诊断 ID。

## 3. 生命周期与重连

```text
create_session -> obtain_ticket -> connect -> ready -> active
  -> flush/stop/cancel -> completed
  -> degraded -> reconnect/new_session | completed
```

- ticket 只能在其有效期、来源、能力和用量上限内使用；SDK 发现过期必须向业务后端申请新会话，不自行刷新长期凭证。
- 建连前失败可遵循 `Retry-After` 进行带抖动重试；已发送音频后失败只在模块 11 的 utterance 边界或用户确认下新建会话。
- SDK 必须以 `event_id` 和 `sequence` 去重/检测缺失，不对音频帧或 final 结果做猜测性重放。
- `cancel` 是幂等的；调用后 SDK 停止采集和本地缓冲，等待 `completed/cancelled` 或超时关闭。

## 4. 编码、缓冲与隐私

SDK 优先选择能力快照允许且本端可稳定产生的压缩编码；音频参数由 `session.ready` 或创建响应协商。SDK 的 jitter buffer、播放 buffer、重连缓存有固定上限，达到上限先停止采集/发送并报告 `flow.warning`，不无限占用内存。

默认遥测只包含 session ID、版本、codec、字节、时延、关闭原因和错误分类。收集原始音频、完整文本、设备标识或网络地址需要产品和隐私策略显式启用。

## 5. 版本与验收

SDK 版本在会话创建时上报，以便策略根据兼容性拒绝不安全的旧版本。SDK 必须通过模块 12 fixtures、模块 13 协议兼容、ticket 重放/过期、Direct/Relay 一致性、断网/慢读/取消、`local_only` 网络审计和 Provider 降级测试。
