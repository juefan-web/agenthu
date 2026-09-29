# M1-1：campus 作业事件派生 Task（真实数据驱动 Study + Time 主线）

2026-09-29 细化：A、B 均已回归，任务从「B 全包」改为**先冻结契约、A/B 并行**的
标准跨边界流程。定性背景（D10 裁定为 M1 范围决策）见 `CURRENT_STATE.md`。

## 阶段 0：契约冻结（A 先行，B 评审，半天内完成）

A 产出决策记录（DECISIONS 新条目）并同步 B，冻结以下语义后双方开工：

1. **派生规则**：`study.assignment.discovered` → 创建 Task；
   `study.assignment.updated` → 幂等更新（deadline/标题变更刷新，
   submitted/graded → 任务完成）。
2. **Task 上游身份**：新列（建议 `source_upstream_id`）+ `(user_id, source,
   source_upstream_id)` 唯一约束；幂等键与 Event dedupe 键
   （`source + upstream_id + semantic_version`）的关系要写清——semantic_version
   变化应更新而非新建。
3. **deadline 时区规则**（关键坑，已预核实）：event `data.deadline` 等字段当前
   是 vendor naive 北京本地串，后端 `UTCDatetime` 对 naive 按 UTC 解释 = 8 小时
   偏移。冻结方向（推荐 a）：a) **客户端必须发 `+08:00` tz-aware ISO，原始串留
   `*_raw` 溯源；Backend 对 naive deadline 拒收（422）**——把规则立在边界上；
   b) handler 按 Asia/Shanghai 解释 naive——向后兼容但把时区假设藏进服务端。
4. **不派生清单**（本轮冻结，后续 M1 项再议）：`study.course.discovered`、
   `time.schedule.entry`、`time.academic_calendar.updated` 不派生 Task。

## 开发者 A（Backend，`feature/assignment-event-derivation`）

- 目标：assignment 事件 → Task 的服务端派生闭环。
- 输出：
  1. Alembic 迁移（up/down 完整）+ fixtures + OpenAPI 快照 + drift 基线同步。
  2. handler 实现：注册 `study.assignment.discovered|updated`；运行在
     `process_event` savepoint 内（C1 语义，handler 失败不丢原始 Event）；
     幂等 upsert；submitted → `COMPLETED` + `completed_at`。
  3. 回归测试：discovered→Task；updated 不重复建；deadline 变更生效；
     submitted→done；tz-aware deadline 正确落库 + naive 拒收（若冻结 a 案）；
     并发同键两事件恰好一个 Task。
- 不负责：客户端 event 载荷构造与 UI。
- 验收：ruff/pyright/pytest 全绿；drift check（双 Zod 源）无漂移；
  迁移 up→down→up 无 drift；真实事件回放 fixture 通过。

## 开发者 B（Client，契约冻结后并行）

- 目标：event 载荷时区正确 + 派生任务在客户端正确呈现。
- 输出：
  1. `events.ts`：`deadline`/`late_deadline`/`publish_time` 转为 `+08:00`
     tz-aware ISO（原串保留 `*_raw`）；顺带审计 `asIso()` 经 `new Date()` 的
     本地时区依赖（用户 OS 非北京时区时 `occurred_at` 回退值的行为），修复并
     加测试。
  2. 任务列表核对派生任务展示：标题/截止时间本地化格式、来源作业可辨识；
     重复采集后任务数不翻倍的可见性。
- 不负责：Backend handler 与迁移。
- 验收：desktop 测试（新增映射用例）+ build 全绿；round-5 真实构建包里
  截止时间无 8 小时偏移。

## 共同验收（round-5，转正后的首个主链验收）

真实账号采集 → `/v1/tasks` 与客户端任务列表出现作业任务（截止时间正确）→
重复采集不重复、deadline 变更刷新 → 从真实任务生成/确认计划 → Focus →
实际时长 → 任务 done。即 AGENTS.md §8 首阶段完整闭环，全程 DevTools 无
CSP violation。两侧完成后 A/B 共同在构建包执行并出具报告。
