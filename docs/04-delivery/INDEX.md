# 交付与治理索引

本目录面向实现者、审阅者和发布负责人。每个代码任务都应先从实施路线进入，再阅读相关架构模块、契约与 fixture。

1. [工程实施总计划与 GitHub 治理](QingYin_工程实施总计划与GitHub治理.md)
2. [DEC-20260829-001：单维护者合并治理（PROPOSED / effective=PENDING）](QingYin_DEC-20260829-001_单维护者合并治理.md)
3. [M1 Rust 核心骨架与运行规范](QingYin_M1_Rust核心骨架与运行规范.md)
4. [M1 契约 Fixture 与 MockProvider 规范](QingYin_M1_契约Fixture与MockProvider规范.md)
5. [M1 实施 Backlog 与 CI 门禁](QingYin_M1_实施Backlog与CI门禁.md)
6. [M1 后续阶段推进计划](QingYin_M1_阶段推进计划.md)
7. [DEC-20261015-001：治理激活执行修复（PROPOSED / effective=PENDING）](QingYin_DEC-20261015-001_治理激活执行修复.md)

新 DEC-20261015-001 是执行修复 profile 的唯一状态源；旧 DEC 标签永久保留历史 PENDING。新状态标签与工程计划 header 受控同步，修复合并仍 PENDING；activation 必须完整私有证据、独立 review、精确 owner 接受、protected merge 和 post 全部 VERIFIED 后才语义 ACTIVE。索引不授予治理或生产权限。

阶段完成后，在本目录新增 `QingYin_<阶段>_验收与复盘.md`，并从此页链接。
