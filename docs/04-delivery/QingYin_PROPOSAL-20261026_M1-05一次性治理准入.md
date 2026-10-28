# QingYin M1-05单维护者治理修订与一次性准入提案

status=PROPOSED/PENDING；authority=UNRESOLVED；formal=BLOCKED；NOT_MERGE_READY。

这是未登记为生效DEC的单文档PROPOSAL。本文以真实唯一维护者为长期前提，不以寻找第二账号或其他维护者为拟议制度前置。不修改旧DEC、六项治理控制或业务，不授予自身权力。当前无合并、activation、改保护或部署授权；正式技术切换能否执行尚未证明。

## 一、三层规则及修订目标

| 来源、固定对象及条款 | 当前效力与边界 |
|---|---|
| `docs/04-delivery/QingYin_工程实施总计划与GitHub治理.md`，27320e74f8cb920add83d6094fb81233dbb29636，blob 72bad2a3d7d72babd4c60554ed8e531ae8d7c841，v0.2 §4第6步及紧随人审段 | 尚未被有效替代的人审前置：讨论解决、必要审批、必需检查；高风险须一名独立第二维护者或安全/SRE真人审阅，不是额外两人，也不要求管理员。Agent不能冒充真人。 |
| `docs/04-delivery/QingYin_DEC-20260829-001_单维护者合并治理.md`，M，blob 1050578bff9c2cadc2e75f20744da6ecda90d53a，header supersedes及§9 | 仍PROPOSED/PENDING。“本决策不能授权自身”；方向不等精确接受；一次bootstrap限PR19，不传播PR17。其双fresh Agent、owner接受、600秒窗口等是待生效方案要求，不是已有效的人审替代权。 |
| `scripts/validate_governance_state.py`，M，blob 75ac048e869f4219e99f4165714810a41711fd13，`validate_candidate_validator_blob`、`validate_activation_diff` | 已安装技术入口实际绑定旧validator并冻结controls，含逐提交历史；不能因规范未ACTIVE而绕过当前检查。 |
| `docs/04-delivery/QingYin_DEC-20261015-001_治理激活执行修复.md`，R，blob 676c4db7f49eb05544a61c2d56fa58b0875d9c2b，§1—3；R validator的`repair_anchor_checks` | R未生效，例外仅该PR20 repair五路径，Rust不变。不是可复用迁移authority。 |

PR20已有10月19日公开owner声明（issuecomment-6257455023），绑定R/M及当时正文；声明存在，底层私有证据本轮未验全，不能复用给R2或本草案。


以上v0.2人审要求尚未被正式替代，这是现行规范事实；不是本提案要求永久寻找其他维护者的设计选择。拟议制度明确改变仓库内部审阅机制，不能假称已经满足旧人审条件。M默认validator仍真实冻结controls；账号admin不等于规范豁免、机器放行或平台保护绕过权。

2026-10-28只读回读确认连接ZhangIvan/ID25630763，repo权限含admin/push；main仍M，PR21仍draft且reviews为空。平台required approval count、CODEOWNER/最近提交审批及ruleset叠加详情仍UNKNOWN；不盲重试已有403端点。若平台强制另一人有效Approve，且无人又不改保护，正式合并无可执行路径；保持draft和隔离工程，不造账号/署名，不绕过。需要时仅请求owner读取最小设置字段，不索要token。

## 二、拟议单维护者制度

唯一owner承担风险与最终精确接受责任，Agent不可代签。候选形成后，接受须绑定真实PR、base/head/tree、路径、风险、原始审计/CI证据、残余有效期及撤销条件，不预签未来SHA。owner不计入审计quorum。

两次分离Agent审计与实现者分开开展：

| 审计线 | 范围与必须交付 |
|---|---|
| A：业务与安全 | 固定规格、租户/actor/runtime授权、状态机、generation/ABA、幂等、取消补偿、终态竞争、secret与日志；给函数/测试映射、可构造序列、finding及未覆盖项 |
| B：治理与供应链 | 精确diff/逐提交历史、权限、Action及runtime、来源/fixture/execution绑定、门禁状态、回滚和证据污染；给独立读取记录、对象/命令、finding与限制 |

分别固定报告后再交叉核对，不互相代写；缺实质来源应为INCONCLUSIVE，不能只引用另一路摘要就报独立通过。会话身份、schema、摘要或metadata检查只能验证声明与绑定，不能证明Agent真实独立、实质审阅充分或消除共享模型/平台相关错误。owner须明确承担该剩余风险。CI不能伪装真人Approve，不制造第二账号、不将Agent标为GitHub人类APPROVED。

拟适用可回滚的仓库代码、契约、文档、测试及CI/治理变更；按语义风险而非文件扩展名分级。CR0/1可简化证据但保留分离审计与精确绑定；CR2/3要求完整两线、真实适用CI、owner精确接受、至少600秒稳定窗口和临门回读。600秒是拟议严格合同，不是当前已生效的人审替代权。

Open P0永远阻断；P1默认阻断，仅非外部强制门、范围有界且可逆的残余可逐项限期接受。secret泄露、租户/客户数据边界缺陷、真实凭据/流量、不可恢复损坏不准残余豁免。法律/合同、第三方或组织审批、生产/发布/外部状态授权、GitHub强制保护均不被替代；CR4不因本制度自动授权。

source/base/head/tree、workflow/runtime、规则或权限变化、证据不全、发现未处置、接受撤回/过期即失效重绑。不得仅凭Action SHA声称平台runtime也被冻结。

## 三、精确supersedes与owner制度决定

未来生效时拟精确替代：

1. v0.2工程总计划§4第6步及紧随独立人工/第二维护者段，仅就本仓库内部可回滚变更，替换为两线分离Agent审计、适用CI和owner精确接受；保留讨论解决、风险与外部门。
2. M旧DEC header supersedes及§9中与新一次性承接冲突的PR19-only bootstrap、PROPOSED六controls冻结和三文件activation合同；旧原文字节保留，新的具名决策明确新适用边界，不修改历史接受。

这是拟改范围，不是现行修改许可，不追溯PR17/19/20。PR20既有owner声明保持原样且只绑定R/M及原正文，不能复用；其底层私有原像本轮未验全，不宣称不存在。R repair未生效、Rust冻结，不能假定先合并/激活PR20即可解锁Rust。

现行有效文本没有已证明的通用单人改制采纳入口。拟由owner明确作出规则创制决定，说明其仓库规则制定责任与依据，接受这是显式替换旧人审要求而非沿旧规则审批通过。该决定的权威及适用性仍须审定，不能由Agent从admin权限推导，不能覆盖外部或平台强制规则。用户设计/准备方向授权不等于此后精确候选接受，也不等于合并或激活。

## 四、分阶段承接及bootstrap边界

阶段A：只准备此非冻结PROPOSED修订文档及候选外审计材料，允许设计和经另行审定的隔离工程。owner制度方向可被明确记录，但不自授旧门内豁免。未来若受保护采纳文本进入main，只形成固定base来源，不自动ACTIVE。

阶段B：技术gate切换另立精确工作包。先审候选外固定审计来源及机器承接合同，再形成实际控制候选并另取owner精确接受；只有合法受保护采纳及post验证完成，才可能判定生效。本轮不执行这些采纳/激活步骤。

旧validator不能批准自身被替换：validate_candidate_validator_blob(8351—8359)仍绑定原blob；validate_activation_diff(761—800，尤其791—792)仍拒绝普通PROPOSED候选触碰六controls及其逐提交历史。不能改EXPECTED_*、跳过selftest、换历史workflow或以候选ACTIVE字符串求绿。候选外审计通过不等于旧required check接受。

当前CI实际命令是python scripts/validate_governance_state.py --self-test。main先从Actions事件取得真实PR/base/head，再调用validate_repository：读取旧DEC、工程总计划与INDEX并执行parse_triplet、validate_source_binding，随后核候选validator blob及冻结diff，最后才运行self-test。新增制度文档或manifest不被旧程序自动读取；--self-test不是绕过真实PR结构检查的入口。

旧self-test独立读取当前ROOT的workflow形成历史fixture，由validate_package_response_semantics核whole-workflow SHA、step/name/run hash、完整action occurrence及context。历史输入与live候选输入须分离、保留冻结来源，不能临时替换workflow或改旧hash库存骗绿。CI成功只证明该精确程序和候选执行的检查，不证明制度采纳或首次切换已生效。

拟信任链为：已明确审定的owner创制合同与固定base来源→候选外已审审计程序/输入记录→真实候选对象→两线实质审计/CI→owner精确接受→合法受保护采纳→post。每一步仅绑定已存在对象，不填写未来SHA。审计源码和registry单向绑定，禁止互嵌最终hash；候选不能自选profile、审计器或授权根，也不import/exec候选代码证明其可信。

当前没有证明旧gate到新gate的合法机器接入路径。若切换必须修改正式validator/CI，须另审确切路径、函数、diff、权威与平台可执行性；未证明则保持BLOCKED。这是仍待解决的工程/采纳断点，不以寻找第二维护者作为唯一方案，也不将owner新决定伪装成旧规则已经批准。

## 五、工程不变量与范围

本次只修订本文件，不新增审计模块、不扩测试矩阵；不重复已有R2工具。R2与采集器仍仅隔离工具，metadata/schema正例不构成Agent独立性证明。后续若需正式入口变更，仅另审scripts/validate_governance_state.py的main/validate_repository/validate_activation_diff/validate_candidate_validator_blob及必要design-contracts.yml接线、INDEX/工程总计划投影；这不是整文件改写授权，六controls当前不变。

M/R历史DEC、validator、workflow及原始证据固定重放；当前候选检查与历史fixture分离。保留ubuntu-24.04、fullhistory、persist-credentials:false、pinned actions、只读permissions、全部GVN及唯一MSRV。保留whole-file、step index/run hash、action occurrence/context、candidate base/head/tree及execution/tree/ordered parents绑定。Node20弃用与runner强制Node24警告另属受控兼容迁移，不顺便改workflow。

release guard脚本在M中不存在，未来业务候选的脚本来源和失败语义须另审，本案不混入H17业务、M1-06或RC01 fake修复。

## 六、验证、回滚与停止

当前修订候选只做diffcheck、唯一文档路径/100644、完整历史/clean、六controls等M，以及现有设计资产和Markdown链接检查。不得冒用PR21旧head运行新候选base-aware CLI；新head未发布时远端CI为NOT_RUN。旧PR21五success仅属于8d04abeef3ae4ef7002c26605653844c987122f7及其合成execution，不能转为本修订的CI。

未来真实候选的contract-fixtures、format-lint、unit、security、msrv均须按实际配置绑定check app、run/job/attempt、head/base/tree、execution及日志。不得改workflow补触发求绿；未触发写NOT_RUN。owner接受、审计、窗口随候选/来源变化失效，不能用旧包或摘要代原像。

未正式采纳前停止隔离候选不影响main；正式回滚仍是合法受保护superseding/revert/forward-fix，保留历史及旧接受，不改保护或hash绕过。基线漂移、权限/来源不明、未知执行结果、关键finding、平台门无法满足或截止不足即停相应阶段。当前无合并、激活、保护修改或部署授权，不联系他人，不请求review，不恢复定时任务。

旧C08 UNKNOWN保持；G14仅三个无害probe和适配后固定R2函数的一次限定证据闭合，不证明历史修复、竞态注入、任意后代或host故障处理。D/G3未恢复。

## 七、准备期历史事实（不作为当前授权）

G16于2026-10-26约00:57—00:59 UTC回读main/PR17/PR20，当时未漂移；不是持续监控。其本地候选88969fff797e5b71f70170301a9faf5f81d3e9ed后来经API重建为PR21旧head8d04abeef3ae4ef7002c26605653844c987122f7，tree相同不意味着接受可转移。旧文档中的未发布表述和2026-10-26 01:54:57UTC截止属于当时准备批次；后续PR21发布与CI已在G18记录，不回写历史receipt。

| 对象 | 固定commit | tree |
|---|---|---|
| M/main | 838faa2633d78058a3e180196cc7e440d8adbf37 | 639accceb367c4b5d3eeb667f49e50493478af8a |
| H17/PR17 | 41b0308e93d595b3978bcf9d9b690da794e0c1aa | 9e98c8db5b83ef89d1346eaf2f21ff4b302fb426 |
| R/PR20 | 51791ae7f438570d5bec52902bf86de878294d11 | 117812811728b2478167e9655701920ef79689e8 |
| R2隔离工具候选 | 4907a9c87a0a0c441b01bd392b90447174941d36 | b9e20f1110f6917271376d033af5283a67e7ed33 |

PR17/20均OPEN未合并。R2仅新增两个审计模块，workflow仍为M；workflow fixture是树外受测文本，既不是实际workflow变更，也不是业务候选。旧D/G3未恢复，不以名称或旧测试代替对象。


G15已审原文SHA256为75ca244aceb79ffee999b4317ec58e95a33c030768cec37391c41e54bdcaa2b9；G15交接归档为69b10ac13544cdb52277ff2b1c705c2bba97b7296559892045503da7bd4e7dbf；G14 receipt为c3e663b439d30cfdfaf34b2eeab3b3489dfe91ed53928350a1606ac690125a7c。旧授权已消费，固定路径/截止不可自动复用。当前批次2026-10-28仅授权云端文档准备、最小验证与本地提交，不发布本修订；整轮05:14:05UTC硬停。候选自身head/tree/hash仅记录树外，避免自引用。

## 八、A/B一次性新规则替代设计（PROPOSED / NOT_APPLIED）

时间说明：2026-10-28本次仅发布方案文档修订并验证，前文G20批次05:14:05UTC/不发布措辞是保留的历史回执，不是当前状态；本轮Agent截至06:15:34UTC，CI可自行完成，本次不构成A/B采纳或激活。

此设计不是M旧程序认可新checker的路径。它提议先合法采纳一份新的规范契约，再以该契约判定唯一一次B；M旧拒绝原样保留。当前规范没有已证明的通用改制入口，owner规则制定权依据及A的合法采纳仍须真实明确确认，不能从admin或泛泛“继续”推导。A/B均无本轮合并、激活或保护修改授权。

A准备：目标checker源文件和候选外auditor实现须先存在、可完整读取并经两路分离实质审计，不在此文填造未来hash。正式A候选拟只新增docs/04-delivery/QingYin_DEC-20261028-001_单维护者一次性检查器切换.md和docs/04-delivery/governance/DEC-20261028-001/checker-transition-v1.json；编号/路径开工前核冲突，冲突停止。旧六controls不变。manifest单向固定已存在target validator的path/blob/SHA256、完整可恢复源字节或公开Git对象定位、auditor来源/SHA、允许B路径、固定制度来源及单次nonce/期限，不依赖未来B head。源字节即使嵌于文档也是高风险待审代码，不因文档后缀免审，不在A执行。

A决议必须逐项明确：仅在A真实合法采纳条件满足后，就一次B显式替代v0.2内部人审前置及旧DEC§9/旧checker冻结对本次target path/blob集合的约束；不谎称旧规则已批准，不改旧DEC原文，不复用PR20例外。不替代法律/外部门/平台强制规则，不覆盖业务、Rust增强或后续迁移。旧M检查FAIL须保存，不能改成PASS。owner须对真实A候选及制度改变作具名精确决定，说明规则制定责任和依据；决定放候选外，避免A内回填自身head/hash。文档或ACTIVE字符串本身不生效，A须满足真实平台流程和已确认的规范采纳条件；A目前尚未存在或被接受。

B执行：base只能是未来实际A受保护采纳commit，不能自行挑同名manifest。B拟仅修改scripts/validate_governance_state.py为A固定target blob，并新增docs/04-delivery/governance/DEC-20261028-001/consumption-v1.json；不改workflow、旧DEC、INDEX/PLAN、业务、锁文件或R2。receipt仅绑定已存在A commit/manifest摘要、nonce、target blob和B base，不写自身未来head。B精确head/tree形成后另作候选外审计和owner精确接受；A不是对任意B的预签。

新checker选择：先由候选外已审固定实现核A真实采纳事实、制度/manifest原字节、target程序字节和执行对象，再运行已绑定新程序。新程序只能从经外部确认的B base读取那个固定manifest，不提供候选CLI/env/profile/标签/正文自选policy或auditor。候选自改A文件、target、路径、nonce、有效期或审计来源都失败关闭。B相对A的全部可达逐提交history限上述两路径，禁止中途越界后恢复、删除重建、rename/mode/symlink/gitlink。保留旧库存用于M/R历史重放，不能将新checker的自测当独立授权。metadata只能检声明，不证明实质独立。

无循环与防重放：A只绑定已有target/auditor字节，不含B head；B引用已存在A commit，不回填自身hash；B head的接受存树外。授权只消费一次真实受保护B采纳，不能由本地成功或CI绿提前消费。receipt路径必须在A base不存在；要求B base及临门main精确等于A采纳commit，消费后main不再等于A且receipt已存在，拒绝第二次。分叉尝试不能继承另一次B接受；过期、漂移、未知写结果停止，不盲重试。平台无expected-base原子CAS的竞态仍为残余：若无法满足精确base/单次及post断言，就不判定生效；不能声称nonce彻底消除并发风险。

结果必须分列OLD_CHECK_RESULT（固定M程序 against B的真实拒绝）、NEW_CHECK_RESULT（A固定新程序的实际结果）和ADOPTION_STATUS。旧程序可由候选外固定源码bootstrap在真实B对象上下文运行，不能执行候选篡改版来冒充旧检查；具体bootstrap实现须另审。新程序exit0只表示新结构成立，formal接受仍依A合同及B独立证据；未知或未采纳输出PENDING/BLOCKED。当前workflow会运行B tree下的candidate脚本，故仅其同名context绿灯绝不是外部来源验证的替代。

平台条件一：若另人Approve/CodeOwner/last-push规则强制他人审批，无人且不改保护则A或B不能完成，禁止造人或自批。条件二：若required workflow/check实质固定旧M程序且其FAIL不可替代，B不能合并，不伪造状态、不忽略失败、不改保护。条件三：若平台现有required context/app确实允许由已合法A授权的新checker真实产生，且没有不满足的独立人审/固定旧workflow规则，则A规范生效、候选外来源核验、B精确接受、真实CI及受保护采纳/post可组成新规则下的条件可行路线；不是M先认可B。还须取得实际contexts/app/workflow约束、审批配置、A权威/采纳原像、target/auditor可恢复来源、两线审计、B接受/执行/历史/真实run及post。当前这些正式前提未齐，平台详情UNKNOWN，不宣布可执行或生效。

回滚和失效：未采纳停止候选；A未消费可由owner撤回其外部接受并保留事实。B采纳后不能复用本次nonce回滚checker；恢复旧blob亦是新的受保护superseding/revert决定，不能让旧DEC约束悄然重启或擦除新旧结果。关键finding、来源不足、target/runtime/权限变化、到期、采纳/post不符即停，保留失败与远端实际事实，不管理员绕过。本设计仅供后续精确裁决，当前不实施、提交或发布A/B。
