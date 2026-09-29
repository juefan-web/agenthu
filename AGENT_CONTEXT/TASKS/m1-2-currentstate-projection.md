# M1-2：CurrentState 投影语义（available_minutes / context）

负责人：开发者 A（Backend）。输入：round-4 附带证据（`available_minutes`/`context`
恒为 null/空、版本空转）+ `backend-m1-tasks.md` A-2。裁定记录：DECISIONS **D-027**。

## 决策（本轮冻结的口径）

### available_minutes

**列语义**：投影输出，**用户 override 优先，否则自动推导**（derived 不落列，
理由见下）。

```
derived = max(0, day_remaining
                    - class_minutes_overlap(now, day_end)
                    - current_task_remaining_estimate
                    - rest_reserve)      # rest_reserve 恒 0，见下
```

- **day_remaining**：`now` 到 `DEFAULT_TIMEZONE` 本地今日 24:00 的分钟数（与
  D-019 today 边界同源；不跨午夜累计）。
- **class_minutes_overlap**：今日 `time.schedule.entry` 事件条目与
  `[now, day_end]` 的重叠分钟和。条目区间 = `data.date` + `data.start_time`/
  `end_time` 按 `DEFAULT_TIMEZONE` 组合后转 UTC；解析失败的条目跳过不计入
  （投影必须鲁棒于 vendor 串形态）。**同 `provenance.upstream_id` 只取
  `timestamp` 最新版本**——dedupe key 含 semantic_version，版本变化会产生新
  Event 行，按 upstream_id 取最新等价于"课表变更/移课后旧条目自动消失"，
  不会双计。无课表数据时该项为 0（数据缺失不空转其他字段）。
- **current_task_remaining_estimate**：`max(0, estimated - actual)`，与
  `planner.remaining_estimate_minutes` 单任务同口径。
- **rest_reserve = 0**：M1 显式决策，不做隐式休息扣除（隐式魔法值会让字段
  不可解释）；用户表达"今天实际只有 X 时间"的手段就是 override。
- **override**：`PATCH /v1/current-state` 的 `available_minutes` 语义不变
  （显式声明），非空时投影直接采用。M1 不提供 override 清除路径（payload
  `None` = 不更新是既有哨兵语义），如需清除由 M1 后续契约变更处理。

**derived 不落列的理由**：① 与 M1-1 并行开发，避免 alembic multi-head 合并
成本——override 的持久化位置不变（`available_minutes` 列继续只承载 override
或 NULL）；② derived 是纯函数输出，Event 流才是事实源（模型注释明言
CurrentState "不是 Event 流的副本"），持久化只是缓存；③ 可观测性通过
`recent_state.available_minutes_breakdown` 记录输入摘要补齐。

### context（当前上下文）

**`current_context` JSONB 列继续只存用户 override**（现状语义不变）。派生
label 在 recompute 时计算，经内部 `CurrentStateRead.context_label` 传递，
`client_view` 优先 override、否则派生值（契约 `ClientCurrentState.context`
字段不变，零契约影响）。优先级：

```
override label
> 在课：{course_name}@{location}          # 今日条目区间覆盖 now
> 专注中：{task title}                    # 活跃 FocusSession（RUNNING/PAUSED）
> 进行中：{task title}                    # 当前任务 IN_PROGRESS
> 即将上课：{course_name}（{n} 分钟后）    # 下一节课 ≤ 30 分钟
> 空闲                                    # 有 pending tasks 但均未开始
> None                                    # 无任何待办（UI 维持"未设置"占位）
```

## 与 B 的对齐清单（round-5 确认，字段/契约不变，仅呈现层）

1. `context` 现有槽位（App.tsx 今日计划标题右侧 meta）将开始出现派生值；
   建议显示 `available_minutes`（如「剩余可用 3h20m」徽标），语义见上。
2. "空闲"作为派生默认值（有待办时）是否合意、None 时占位文案，由 B 定；
   文案调整属客户端，不改口径。
3. 本口径若需微调（如休息扣除），走 DECISIONS 变更而非静默改实现。

## 实现（本轮完成）

- `services/current_state.py`：`_today_schedule_entries`（窗口内按 upstream_id
  取最新 → 过滤今日）、`_class_minutes_overlap`、`_derive_context_label`
  （含活跃 FocusSession 查询）、recompute 内计算 derived + breakdown 写入
  `recent_state`。
- `schemas/current_state.py`：`CurrentStateRead.context_label`（内部字段，
  不进 OpenAPI/客户端契约）。
- `services/client_view.py`：context 取 `context_label`（override 优先逻辑在
  recompute 内）。

## 验收（本文件 + D-027）

- 回归测试：无数据（derived = 剩余日分钟、context None/空闲分支）、课表覆盖
  now（在课 + 扣减）、即将上课（≤30min）、override available_minutes/label
  优先、upstream_id 新旧版本只取最新、当前任务估时扣除。
- round-5/round-6：真实采集数据下字段非空且合理（课表真实进入 Event 流后，
  课中采集应显示「在课：…」且 available_minutes 明显低于剩余日分钟）。

## 不负责

- 课表数据的客户端展示细节；`time.schedule.entry` 的 Task 派生（M1-1 冻结的
  不派生清单）；multi-worker / 定时重算触发器（另立决策）。
