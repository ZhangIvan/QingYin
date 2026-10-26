# QingYin M1-05一次性治理准入提案（未登记为生效DEC）

status=PROPOSED/PENDING；authority=UNRESOLVED；formal=BLOCKED；NOT_MERGE_READY。

这是单文档PROPOSAL，不占用正式DEC编号，不改变旧DEC或六项控制。

## 一、目的与固定事实

本提案供独立真人审阅，讨论如何合法采纳一次性控制迁移，不授予自身或后续代码权利。G16于2026-10-26约00:57—00:59 UTC经GitHub连接器刷新main、PR17、PR20：固定对象未漂移；这是一次回读，不代表持续监控。

| 对象 | 固定commit | tree |
|---|---|---|
| M/main | 838faa2633d78058a3e180196cc7e440d8adbf37 | 639accceb367c4b5d3eeb667f49e50493478af8a |
| H17/PR17 | 41b0308e93d595b3978bcf9d9b690da794e0c1aa | 9e98c8db5b83ef89d1346eaf2f21ff4b302fb426 |
| R/PR20 | 51791ae7f438570d5bec52902bf86de878294d11 | 117812811728b2478167e9655701920ef79689e8 |
| R2隔离工具候选 | 4907a9c87a0a0c441b01bd392b90447174941d36 | b9e20f1110f6917271376d033af5283a67e7ed33 |

PR17/20均OPEN未合并。R2仅新增两个审计模块，workflow仍为M；workflow fixture是树外受测文本，既不是实际workflow变更，也不是业务候选。旧D/G3未恢复，不以名称或旧测试代替对象。

## 二、规则层次与两项待决

| 来源、固定对象及条款 | 当前效力与边界 |
|---|---|
| `docs/04-delivery/QingYin_工程实施总计划与GitHub治理.md`，27320e74f8cb920add83d6094fb81233dbb29636，blob 72bad2a3d7d72babd4c60554ed8e531ae8d7c841，v0.2 §4第6步及紧随人审段 | 尚未被有效替代的人审前置：讨论解决、必要审批、必需检查；高风险须一名独立第二维护者或安全/SRE真人审阅，不是额外两人，也不要求管理员。Agent不能冒充真人。 |
| `docs/04-delivery/QingYin_DEC-20260829-001_单维护者合并治理.md`，M，blob 1050578bff9c2cadc2e75f20744da6ecda90d53a，header supersedes及§9 | 仍PROPOSED/PENDING。“本决策不能授权自身”；方向不等精确接受；一次bootstrap限PR19，不传播PR17。其双fresh Agent、owner接受、600秒窗口等是待生效方案要求，不是已有效的人审替代权。 |
| `scripts/validate_governance_state.py`，M，blob 75ac048e869f4219e99f4165714810a41711fd13，`validate_candidate_validator_blob`、`validate_activation_diff` | 已安装技术入口实际绑定旧validator并冻结controls，含逐提交历史；不能因规范未ACTIVE而绕过当前检查。 |
| `docs/04-delivery/QingYin_DEC-20261015-001_治理激活执行修复.md`，R，blob 676c4db7f49eb05544a61c2d56fa58b0875d9c2b，§1—3；R validator的`repair_anchor_checks` | R未生效，例外仅该PR20 repair五路径，Rust不变。不是可复用迁移authority。 |

PR20已有10月19日公开owner声明（issuecomment-6257455023），绑定R/M及当时正文；声明存在，底层私有证据本轮未验全，不能复用给R2或本草案。

待决A：谁依据哪条现行有效条款采纳一次性替代契约？须由合法维护责任人与独立真人审查落实，精确owner接受不能由Agent或方向授权代签。

待决B：旧gate如何合法承接新gate？须明确候选外固定审计器来源、可信base和精确绑定；不能让候选选择自身hash/profile或以ACTIVE文字自选政策。目前没有证明通用承接入口存在。即使补齐人审和接受，也不等于旧validator会批准新validator。

## 三、最小路线及工程合同

第一阶段仅准备单新增文档供审阅。未来如另获发布及受保护采纳授权，文本进入main只取得固定base来源，PROPOSED不自动生效。第二阶段须先裁定A/B，再另审精确diff、隔离实现及验证；此前禁止正式控制实施。这是可行性待验证的两阶段路线，不是已证明合法入口，不建议先merge/activate PR20解锁Rust。

拟另审写路径如下，均NOT_APPLIED：

| 路径 | 目的、允许增量与禁止范围 |
|---|---|
| 新具名`docs/04-delivery/QingYin_DEC-<待定编号>_<待定名称>.md` | 精确列supersedes及接受/生效合同；编号、授权根尚待审，不改旧DEC。 |
| `scripts/validate_governance_state.py`及未来具名独立模块 | 仅合法承接机制及历史/当前来源分离；现有两模块与采集器只是隔离工具，不接入正式默认入口自证可信。 |
| `.github/workflows/rust.yml` | 未来仅审定的all-features/locked、strict rustdoc、doctest、release guard及paths增量；禁止重复MSRV或削弱保护字段。 |
| `.github/workflows/design-contracts.yml` | 仅在合法入口确需接线时另审精确命令；当前没有修改授权。 |
| `docs/04-delivery/INDEX.md`、`docs/04-delivery/QingYin_工程实施总计划与GitHub治理.md` | 仅经审定投影及依赖说明；不改旧接受事实、不以副本激活规则。 |

release guard脚本在M中尚不存在，不能只增加workflow调用就宣称运行完备。未来须另审业务候选中的`scripts/validate_security_release_guard.py`来源、接口与失败语义；本控制提案不夹带H17业务、M1-06或RC01修复。审阅者应先核对每项增量是否真的必要；无需变动的文件保持原字节，不能把路径表当作整文件修改许可。

不得由此表自动扩大到六controls。M/R冻结源码、原始包及各自selftests保留；历史fixture与当前候选检查分离，不换旧workflow骗绿。新workflow须保留ubuntu-24.04、full history、persist-credentials:false、pinned actions、只读permissions、全部GVN证据及唯一增强MSRV。逐项绑定whole-file、step index/run hash、action occurrence/context，以及candidate base/head/tree、实际execution commit/tree/有序parents；tool、fixture、业务候选各自绑定，互不代替。缺合法根、原像或精确diff即停。

## 四、验证、退出与回滚

以下映射来自M，不表示检查通过；未来实际候选须重新核命令及真实run/job/attempt/log，当前全部NOT_RUN：

| check | workflow / job | 命令类别 |
|---|---|---|
| contract-fixtures | design-contracts.yml / design-contracts | 设计资产、Markdown链接、原治理`--self-test` |
| format-lint | rust.yml / format-lint | fmt、locked check/Clippy、边界与fixture校验 |
| unit | rust.yml / unit | locked workspace tests |
| security | rust.yml / security | secret regression与security/observe tests |
| msrv | rust.yml / msrv | Rust1.85.0 locked全workspace/all-targets/all-features check |

source/base/head/tree/workflow任一改变，旧CI、review、接受及窗口证据失效。现行真人审阅前置仍须满足；若未来合法采纳M/R式方案，双fresh审查、trusted-control audit、owner精确接受、至少600秒稳定窗口、临门回读和post亦须按其有效条款执行。提案可要求这些更严证据，但不据此提前取得人审替代权。缺必要项、Open P0/未接受Open P1、P2未处置或讨论未解决即停。

回滚仍需合法受保护revert/forward-fix路径；未生效前停止候选不等于回滚main。不得改保护、改历史hash或重写证据求绿。

旧C08证据链UNKNOWN保留。G14仅证明三个无害probe和一次适配后固定R2函数的WORKFLOW拒绝及新证据闭合；不是原CLI原样运行，也未测竞态注入、任意后代、host故障或普遍物理清理保证。

## 五、授权边界与最小外部输入

本轮已授权云端准备此单文档、最小验证和本地提交，不再申请同一准备授权。发布须另获绑定具体单文档commit的分支推送、draft PR及原有CI授权；仅向指定reviewer发送一次GitHub review request须另行明确同意，不默认邮件或私聊。当前不发布、不联系他人。merge、activation、protection修改和deploy仍禁止，不是自动尾项；改保护没有默认必要性。

真正待维护者落实的是现行认可的权威路线、独立真人角色及其接受，随后才是新候选精确owner接受和合法受限原像读取。只需文件位置、清单及读取权限，不索要token、不宣称私有包不存在。本草案及本轮消息均不作为正式批准记录，不自动向用户发新批准问题。

## 六、送审合同与权限核实

责任人须说明真实GitHub身份、维护角色和可决定的事项，不能仅凭仓库同名推定当前用户身份。指定的一名独立真人应审阅精确提案、规则原文、两个待决问题、风险与回滚，给出理由、发现及未解决事项；模板默认PENDING/CHANGES_REQUIRED，不预填APPROVED。

能提交review不等于Approve可计入仓库门槛。当前具体reviewer权限、保护审批详情仍UNKNOWN；M/R均未发现CODEOWNERS文件。人选确定后先用现有合法只读连接核查，确实不可读取才请求最小设置页面或脱敏导出；不盲重试已403端点，不索取凭据，不建议改变保护。

单文档送审不以取得R私有原始包为前提。只有未来裁定明确依赖某历史证明时，才列所需原像文件、合法受限位置和读取权限；公开声明不等于底层证明已验全，也不能因不可读宣称不存在。PR20旧声明保持不动、不复用、不追加评论。

## 七、阶段、验证与停止

第一阶段输入是固定M、已审G15和现行规则；产物是本单文档及树外PR草稿、真人review/owner模板、操作手册、证据读取清单和manifest。全文静态审查后，仅作一个诚实身份本地提交；候选自己的head/tree/doc hash只记树外，避免自引用。本任务使用工具默认codex/前缀，与CONTRIBUTING原分支枚举不同；不为命名修改规范。

验收：相对M仅本文件新增100644，六controls磁盘和HEAD逐字节等M，M祖先、线性完整历史、clean、diffcheck；设计资产、链接、原M治理self-test各一次。原CLI显式base-aware上下文必须有真实PR号；当前无远端PR，不虚构或借用PR17/20。可运行不带PR上下文的真实CLI本地结构检查，但不得称为base-aware候选准入或远端检查通过。失败保留日志，不改validator/hash求绿。

第二阶段仅在主审审定精确材料后讨论具体发布授权；原有CI的真实execution及review绑定仍待发布后取得。单文档进入main也不会自动解决A/B或激活政策。权威契约和机器承接机制未裁定，正式控制实施保持BLOCKED。若解除正式冻结必须受保护采纳/激活，本轮只能解除准备与审阅材料不足，不能承诺完全解除正式准入。

停止或文档返工只影响本隔离分支；不重写旧证据、不回滚main、不改保护。任何base、source、候选变化须重新绑定材料；不自动扩至业务变基、M1-06或fake修复。当前没有新增权限请求，亦不自动向任何人发送批准问题。

## 附录：历史证据与恢复边界

G15已审原文SHA256：75ca244aceb79ffee999b4317ec58e95a33c030768cec37391c41e54bdcaa2b9。
G15交接归档SHA256：69b10ac13544cdb52277ff2b1c705c2bba97b7296559892045503da7bd4e7dbf。
G14 receipt SHA256：c3e663b439d30cfdfaf34b2eeab3b3489dfe91ed53928350a1606ac690125a7c。

恢复须先核归档、manifest及Git对象；旧执行授权已消费，固定路径/截止脚本不可直接复用。G14新证据闭合不修复历史C08 UNKNOWN；D/G3未恢复，W1只是fixture。本轮一次授权硬截止2026-10-26 01:54:57 UTC（09:54:57 UTC+8），01:49 UTC开始清理，不恢复定时任务。
