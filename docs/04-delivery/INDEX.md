# 交付与治理索引

本目录面向实现者、审阅者和发布负责人。每个代码任务都应先从实施路线进入，再阅读相关架构模块、契约与 fixture。

1. [工程实施总计划与 GitHub 治理](QingYin_工程实施总计划与GitHub治理.md)
2. [DEC-20260829-001：单维护者合并治理（PROPOSED / effective=PENDING）](QingYin_DEC-20260829-001_单维护者合并治理.md)
3. [M1 Rust 核心骨架与运行规范](QingYin_M1_Rust核心骨架与运行规范.md)
4. [M1 契约 Fixture 与 MockProvider 规范](QingYin_M1_契约Fixture与MockProvider规范.md)
5. [M1 实施 Backlog 与 CI 门禁](QingYin_M1_实施Backlog与CI门禁.md)
6. [M1 后续阶段推进计划](QingYin_M1_阶段推进计划.md)

DEC 状态标签是受控副本：activation evidence PR 必须以 `main` 为 base，在同一 commit 中原子同步本页、DEC 和工程实施总计划 header，并由 `scripts/validate_governance_state.py` 对净 diff、`base..candidate` 全可达逐提交 raw history、PR #19 后六控制文件 lineage、冻结区、三处值关系及完整 activation evidence binding 做失败关闭断言；不一致时一律保持 `PENDING`。本页是可演进索引，除状态标签外不构成治理决策权威；治理语义只能由具名 DEC 修改。

阶段完成后，在本目录新增 `QingYin_<阶段>_验收与复盘.md`，并从此页链接。
