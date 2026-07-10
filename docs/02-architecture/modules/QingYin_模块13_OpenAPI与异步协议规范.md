# QingYin 模块 13：OpenAPI 与异步协议规范

版本：v0.2
目标：将公开接口从“文字描述”冻结为可验证、可生成 SDK、可兼容演进的协议资产。本文定义规范要求，不创建接口代码或规范文件。

## 1. 规范资产与范围

QingYin 维护三类独立但互相引用的规范资产：

| 资产 | 覆盖内容 | 规范格式 |
| --- | --- | --- |
| Control API | 会话创建、能力查询、状态查询、管理操作 | OpenAPI 3.1 |
| Streaming API | ASR/TTS/Realtime WebSocket 握手、消息、二进制帧、关闭行为 | AsyncAPI 3.x + 模块 12 字段词典 |
| Admin API | 租户、Provider、策略、容量卡、审计的受限管理操作 | 独立 OpenAPI 3.1 文档 |

公开协议与管理协议必须分离：管理接口不与业务 API 共用网关路由、权限范围或客户端 SDK。健康探针、metrics 和内部 Worker RPC 不进入公开 OpenAPI。

## 2. 公开 API 面

| 接口 | 目的 | 幂等要求 | 认证方式 |
| --- | --- | --- | --- |
| `POST /v1/sessions` | 校验请求、选择数据面、生成会话 lease | 必须支持 `Idempotency-Key` | 项目 API Key/Service Account |
| `GET /v1/sessions/{session_id}` | 查询可公开的会话状态与用量摘要 | 天然幂等 | 同一租户主体 |
| `DELETE /v1/sessions/{session_id}` | 取消尚未结束的会话 | 重复调用结果一致 | 同一租户主体 |
| `GET /v1/capabilities` | 查询租户允许的规范能力 | 天然幂等 | 项目 API Key/Service Account |
| `POST /v1/tts/stream` | 一次性 TTS 流式输出 | `Idempotency-Key` 仅保护创建；音频流不可重放 | 项目 API Key/Service Account |
| `WS /v1/asr/stream` | Relay/Local 实时 ASR | 首帧 `event_id` 去重；音频帧按序 | 一次性 session ticket |
| `WS /v1/tts/stream` | 增量文本到音频 | `text_commit` 使用 event ID 去重 | 一次性 session ticket |
| `WS /v1/realtime` | 双工实时会话 | 所有控制事件带 event ID | 一次性 session ticket |

`POST /v1/sessions` 是所有流式会话的授权和准入入口。浏览器与移动端不得把长期项目密钥放入 WebSocket query string；它们只使用绑定租户、能力、来源、过期时间和最大用量的一次性 ticket。

Workspace 不由普通客户端请求体任意指定，而由 API Key/Service Account 的绑定范围或受控服务端委派令牌解析。任何跨 Workspace 管理操作只能通过独立 Admin API 与明确权限执行。

## 3. 公共请求与响应约定

每个 OpenAPI operation 都必须定义：请求/响应 schema、必填与可选字段、最大长度、枚举、鉴权范围、成功与失败状态、幂等语义、限流 scope、审计字段和示例。

标准请求头：

| Header | 要求 |
| --- | --- |
| `Authorization` | 服务端 API 调用使用，不出现在浏览器 URL 或日志 |
| `Idempotency-Key` | 创建会话与可重试的非幂等请求必须携带；作用范围为租户+接口+请求摘要 |
| `X-Request-Id` | 客户端可提供，Gateway 不可信任其唯一性并生成内部 trace ID |
| `X-QingYin-Api-Version` | 可选的显式版本协商；缺省使用路径对应的稳定版本 |
| `Content-Type` / `Accept` | 严格校验；音频流与 JSON 控制响应不可混淆 |

标准响应头：`X-Request-Id`、`RateLimit-Limit`、`RateLimit-Remaining`、`RateLimit-Reset`；当请求尚未被接受时使用 `Retry-After`。具体额度不由 API 文档写死，而引用有效的租户策略和容量卡。

## 4. 流式与二进制契约

- 建连后首个控制消息必须是模块 01 定义的 `start`，未完成 `session.ready` 前的音频帧一律拒绝。
- 控制事件遵循模块 12 的事件信封，且 `event_id`、`sequence`、`schema_version` 必填。
- 二进制音频帧由已协商的 codec/container/sample rate 定义；帧大小、最大乱序窗口、最大持续速率和关闭码均写入 AsyncAPI。
- HTTP chunked TTS 必须通过响应头或首个 metadata 事件提供与 `tts.audio_started` 等价的信息。
- `cancel`、`stop`、超时、ticket 过期和 Provider 断开都必须映射到规范关闭事件与错误码，不能只依赖 WebSocket close code。

## 5. 错误、限流与幂等

错误使用模块 12 的 canonical code。HTTP 只在入口请求阶段返回相应 4xx/5xx；进入流式会话后，使用 `session.error`、`flow.warning` 或 `flow.busy`。

幂等记录至少保存到超过客户端最大重试窗口；相同 key + 相同摘要返回原结果，不同摘要返回 `invalid_request`。禁止对已经接受音频或已经写出的 TTS 字节执行隐式重放，避免重复识别、重复计费和音频重复播放。

## 6. 版本治理

- `v1` 只允许增加可选字段、可选事件和新 operation；不允许改变已有字段语义、类型、认证要求或状态码语义。
- 破坏性变更发布新主版本，通过独立路径和独立 AsyncAPI 文档承载。
- 每个变更需要 schema diff、兼容性分类、客户端影响、弃用日期、迁移指南和回滚计划。
- 规范文件必须在 CI 中执行 schema lint、reference 校验、示例校验、breaking-change 检测和模块 12 fixture 验证。

## 7. 发布验收

OpenAPI/AsyncAPI 在发布前必须满足：所有 operation 有鉴权和限流描述；所有响应都可映射到模块 12；浏览器票据流程不包含长期密钥；幂等、取消、错误和版本兼容均有测试 fixture；管理 API 与公开 API 的权限边界经越权测试验证。
