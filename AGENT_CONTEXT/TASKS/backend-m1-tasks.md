# 开发者 A：M1 期任务清单（2026-09-29 细化）

主线任务见 `m1-1-assignment-event-derivation.md`（阶段 0 契约冻结 + Backend
实现）。本文件是 A 的独立任务，按优先级排序。

## A-1（快速还债，先做）：D9 明文 cookie 边界联合 review 补录

- 背景：merge-3 的 D9 修复为 `zhjw.cic.tsinghua.edu.cn` 单 host 开了
  `http:80` 窄口（该 host 会话 cookie 明文传输），B 已声明边界变化但 A 当时
  临时不在，review 与 DECISIONS 编号悬空（CURRENT_STATE 有记录）。
- 输出：对 `allowed_campus_url` 窄口实现出具书面 review（范围最小性、重定向
  继承、伪造测试覆盖）；DECISIONS 新条目（编号顺延）记录裁定与理由。
- 验收：DECISIONS 条目落地，review 意见附在条目或 `client-merge3` 任务文件。

## A-2（M1-2 预研）：CurrentState 投影语义定义

- 背景：round-4 观察到 `available_minutes`/`context` 恒为 null/空（版本在
  bump、字段空转）；M1-1 落地后真实任务会进来，投影语义需要跟上。
- 输出：决策记录 + 实现提案——`available_minutes` 计算口径（课表占用、
  当前任务估时、休息段）、`context` 推导（当前时段/课程/任务）；与 B 对齐
  UI 展示需求后冻结，再实现投影与测试。
- 验收：决策记录 + 投影实现 + 回归测试；round-5 或 round-6 在真实数据上
  验证字段非空且合理。
- 不负责：课表数据的客户端展示细节。

## A-3（backlog，不阻塞，按窗口排期）

1. **events 列表 keyset 分页**：当前 offset/limit，`next_cursor` 已按 D-022
   弃用；事件量上来后补 keyset 游标（先决策再动契约）。
2. **多 worker 限流升级 Redis 版**：`core/rate_limit.py` 已预留接缝；部署
   多 worker 前完成（部署期任务）。
3. **Memory/Grounding（M3）技术预研**：pgvector 索引策略、资料解析 Worker、
   引用（页码/时间点）返回契约草案——M1 收尾后启动，先 ADR 后实现。

## 边界提醒

- M1-1 的 schema 变更（`source_upstream_id`）由 A 主导实现（B 回归前占位
  实现已取消，见 m1-1 文件重构说明）；迁移、fixtures、OpenAPI、drift 基线
  同步是完成定义的一部分。
- B 若在 M1-1 联调中需要契约调整，走「先同步 OpenAPI 与迁移说明」流程，
  不单边改字段。
