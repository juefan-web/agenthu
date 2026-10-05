# M5 phase-0：数据生命周期与数据控制双草互审

Status: **r1 初稿已备齐，等待 A/B 互审与协调人裁定（2026-10-05）**。
输入：M4收口 bf02eeb、D-030、M3删除图、M4五项结转；
总指导见 [m5-planning-guidance](m5-planning-guidance.md)。

## 0. 任务边界

- 目标：实现前冻结导出/删除、授权管理、本地隔离与运维共同契约。
- 输入：基线、现行代码、许可原文。
- 输出：A/B 修订、对方 head-bound 评审、字段矩阵、协调人 Decision、
  实施切片；E7 预期账面随契约同步修订。
- 负责范围：文档、状态/文案、失败路径、迁移与回滚方案。
- 不负责范围：冻结前实现、真实数据删除、密钥值、代签或清理其他工作区。
- 验收：冻结清单闭合，无影响开工的 TBD；未触发优化有明确结转条件；
  双稿各持对方对准确 head 的批准。

## 1. A：生命周期、导出删除与运行契约

初稿：[m5-data-lifecycle-ops-contract](m5-data-lifecycle-ops-contract.md)。

负责 Backend/models/migrations/worker/storage/auth/trace/备份手册。
先补齐依赖清单（含JSON/缓存）、确认锁、屏障/并发、保留期、
导出包、字段和错误。旧数据缺血缘必须有保守清理或阻塞规则。
A 核 B 稿：副作用是否等于文案、账号停用后回执如何读取、
队列不跨账号/不重传、grant scope是否真正执行。

## 2. B：数据控制、授权与本地生命周期契约

初稿：[m5-data-controls-grants-client-contract](m5-data-controls-grants-client-contract.md)。

负责 React/Tauri/SQLite/Stronghold/contracts、删除入口、grant面板、
通知与模型同意说明、OneTHU copied-file许可盘点。
B 核 A 稿：逐字段可渲染，nullable/optional明确，异步删除不伪造成功，
跨设备残留可理解，错误/遥测不含密钥和正文。

## 3. 冻结清单与执行协议

| 必须落案 | 交叉核对 |
| --- | --- |
| 删除图、记忆版本链、修正/派生内容边界 | A §1–3 ↔ B §2/4；valid_to与supersedes_id旧行复活 |
| Preview/Operation/Receipt/Manifest字段、枚举、时间/可空性 | A §4 ↔ B §1/3；逐字段镜像，不仅靠单向drift |
| L2预览确认、重传、快照变化、屏障 | A §2/4 ↔ B §2；不自动授权删除 |
| 旧DELETE/客户端/队列与代际兼容 | A §7 ↔ B §4；淘汰与发布顺序一起签认 |
| grant词汇、可执行限制、撤销竞态 | A §8 ↔ B §5；未实现项不得成为可授权选项 |
| 数据四问、备份/供应商期限、离线设备 | A §5/6 ↔ B §3/4/6 |
| trace、共享限流断供、恢复、真实key证据 | A §6 ↔ B §6；明确操作者 |
| 许可/public/source/binary发布门 | 总指导 §4 ↔ B §6；未澄清不算通过 |
| expected counts、零残留查询、故障恢复 | 双方核 [E7](m5-e7-acceptance.md)，协调人裁定出口 |

流程：各修自己的稿 → 审对方准确commit → 意见编号闭环 →
语义修订重新互审 → 协调人登记采纳/例外 → 小PR开工。
零代码rebase延续批准须声明前后SHA与diff依据；
语义变更不得用延续协议跳过重审。

当前初稿已可评审，**不表示 A/B 已批准、协调人已冻结或 E7 已通过**。
