# QingYin 模块 05：控制面、租户、用量与安全

版本：v0.2

## 1. 身份模型

```text
Organization -> Workspace -> Project -> Environment -> API Key / Service Account -> Session
```

Organization 是公司级 SaaS 租户；Workspace 是公司内部部门、业务线或交付团队的强制隔离边界。API Key 只用于创建或控制会话，不能直接等价为 Provider 凭证。Gateway 认证后生成内部 `principal`，将其绑定到组织、Workspace、角色、策略集、限额和审计上下文。

## 2. 访问控制

角色：`owner`、`admin`、`developer`、`operator`、`viewer`。权限最小化到项目与环境。生产密钥不得用于测试环境；控制台密钥必须可撤销、可轮换、有最后使用时间。

任何会话都需校验：允许的任务、语言、音色、目标区域、Provider allow-list、并发、每日用量和数据策略。策略判定记录版本号，便于事后重放判断。

## 3. 密钥与凭证

- Provider 主密钥只存在服务器密钥存储/环境注入中，不写入代码、配置示例、日志或前端。
- Direct 仅签发最小权限、单次、短时票据；票据与本地会话状态同时失效。
- 采用按 Provider 账户隔离的密钥引用，如 `secret_ref`，而非把明文填入能力注册表。
- 轮换要支持双密钥重叠期；Adapter 必须能在不影响现有会话的情况下换新建连凭证。

## 4. 配额、计量与成本

计量单位不强行统一为一个数字。ASR 按音频时长，TTS 按字符/音频时长/模型计费单位，Direct 还需以 Provider 账单对账。系统内部记录：

```text
tenant_id, project_id, session_id, provider_id, task,
audio_in_ms, audio_out_ms, chars, cache_hit, direct_or_relay,
estimated_cost, provider_request_id, policy_version
```

实时准入同时经过四个令牌桶：租户连接数、租户活跃流、Provider 并发、Gateway 音频字节。每个桶都有独立 `retry_after_ms` 计算。用量为估算值时必须带 `estimated=true`，不得作为不可申诉账单唯一依据。

## 5. 数据治理

- 默认不持久化原始音频和完整转写；产品若需保存，必须由租户显式打开并配置保留期。
- 指标使用不可逆 session 标识；日志只保留长度、编码、时延、错误分类和已脱敏的 Provider request ID。
- 允许训练/质量采样前必须具备显式开关、抽样比例、脱敏规则、访问审批和删除流程。
- `local_only` 是硬约束：路由和故障降级都不得发送到云 Provider。

## 6. 管理 API 边界

控制台和 Admin API 可以管理 Provider 启停、路由策略、音色目录、配额、密钥引用、观察数据和审计记录；不允许通过管理 API 读取密钥明文或下载默认不保存的音频。Provider 切换必须支持 preview，展示受影响租户与能力差异，再发布。
