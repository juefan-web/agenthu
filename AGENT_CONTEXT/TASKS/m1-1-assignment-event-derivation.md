# D10 / M1-1：campus 作业事件派生 Task（真实数据驱动 Study + Time 主线）

负责人：开发者 B（A 临时不在；本任务涉及 Backend handler 与可能的 schema 变更，
按本轮授权由 B 实施，**A 回归后必须补充 review**，涉及迁移的按仓库规则同步
fixtures/OpenAPI/契约）。定性：**M1 范围决策，非 PR #1 缺陷**（裁定依据见
`CURRENT_STATE.md` 2026-09-29 条目）。

## 背景（round-4 验收确认）

100 条真实 campus 事件全部被接受，但 Backend handler 注册表只有
`focus.started`/`focus.completed`/`task.*` 三个 pattern
（`backend/services/event_handlers.py:92,100,141`），与客户端发出的
`study.course.discovered`、`study.assignment.discovered|updated`、
`time.schedule.entry`、`time.academic_calendar.updated`
（`apps/desktop/src/adapters/campus/events.ts`）**零交集**——真实数据无法
驱动 Task/Plan/Focus。

## 范围

**必做（M1-1 核心）**：

1. `study.assignment.discovered` → 创建 Task（title、deadline、来源 Event 关联、
   estimate 缺省）；`study.assignment.updated` → 幂等更新（deadline/标题变更、
   submitted/graded 后任务完成或标记）。**幂等键必须基于 assignment 上游身份**
   （如 `assignment_id`/dedupe 语义），重复采集产生 updated 事件不得重复建 Task。
2. **时区坑（必须处理，已预核实）**：event `data.deadline`/`late_deadline`/
   `publish_time` 目前是 vendor 原始 naive 字符串（"YYYY-MM-DD HH:mm" 北京本地
   时间），而后端 `UTCDatetime` 规则是 naive→按 UTC 解释——直接解析会产生
   8 小时偏移。修复方向：客户端在 `events.ts` 里把这些字段转为带 `+08:00` 的
   tz-aware ISO（原始串可另存 `*_raw` 供溯源），或 handler 侧显式按
   Asia/Shanghai 解释；二选一并加回归测试。顺带核查 `asIso()` 对 naive 串经
   `new Date()` 的本地时区依赖（用户 OS 时区非北京时的行为）。
3. 回归测试：discovered→Task、updated 不重复建、deadline 变更生效、
   submitted→任务完成、时区正确性。

**暂缓（后续 M1 项，本任务不做）**：`study.course.discovered`（课程→资料域，
不派生 Task）、`time.schedule.entry`/`time.academic_calendar.updated` →
CurrentState 的 `context`/`available_minutes`（当前为 null，待真实任务/目标
接入后再定投影语义）。

## 实施注意

- Task 模型当前无上游身份列的话需要加（如 `source_upstream_id` + 唯一约束），
  属 schema 变更：迁移 + fixtures + OpenAPI/契约同步 + drift 基线，A 回归后
  review。
- handler 在 `process_event` 的 savepoint 内运行（C1 语义）：handler 失败不得
  丢原始 Event。
- 派生 Task 的权限等级与 Plan 生成沿用现有链路（D-019/D-023 不变）。

## 验收标准（round-5 构建包）

- 真实账号采集 → `/v1/tasks` 出现作业任务（标题、截止时间正确，无 8 小时
  偏移），客户端任务列表可见；重复采集不产生重复任务，deadline 变更后刷新。
- 从真实任务出发走通：计划生成/确认 → Focus → 实际时长 → 任务 done——
  **真实数据驱动的完整 Study + Time 闭环**（AGENTS.md §8 首阶段验收主链）。
- 双侧 CI 全绿；联合 drift check 无漂移；A 回归 review 完成记录。

## 后续 M1 排队（不阻塞本任务）

导入适配层其余部分（手动录入 UI）、CurrentState 投影丰富化、Memory/Grounding
（M3）之前的主链稳定性。
