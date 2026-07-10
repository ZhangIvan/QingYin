# QingYin 文档索引

本目录按“为什么做 -> 如何设计 -> 如何交付”的顺序组织。新成员应从本页开始，不需要先阅读全部模块文档。

## 建议阅读路径

1. [项目 README](../README.md)：当前阶段、仓库规则和入口。
2. [来源与产品动机](00-origin/INDEX.md)：理解 QingYin 的最初问题和约束。
3. [调研与历史结论](01-research/INDEX.md)：了解被保留的早期分析，以及哪些结论不可直接当作生产承诺。
4. [架构设计](02-architecture/INDEX.md)：系统边界、模块、契约、数据与验收基线。
5. [产品与控制台](03-product/INDEX.md)：已确认的后台页面、数据映射和前端实现前提。
6. [交付与治理](04-delivery/INDEX.md)：阶段 Backlog、GitHub 协作、CI、审阅和实现入口。

## 目录规则

- `00-origin` 保存需求来源，不随实现重写。
- `01-research` 保存早期调研和对比；与 v0.2 设计冲突时，以 `02-architecture` 为准。
- `02-architecture` 是后端、协议、数据、可靠性和验收的设计事实来源。
- `03-product` 只存经确认的产品/前端设计及其数据映射。
- `04-delivery` 存实施路线、任务拆分、CI、审阅和阶段复盘。
- 新文档先放入对应目录并更新该目录的 `INDEX.md`；新模块再更新 `02-architecture/modules/INDEX.md`。
