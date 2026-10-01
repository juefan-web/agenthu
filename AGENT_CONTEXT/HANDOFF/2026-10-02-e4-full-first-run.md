# E4 全链首跑记录（2026-10-02，A 执行）

**结论：`AGENTHU_E4_FULL=1` 全链 2 passed（e4-seed 1.9s + 全链 28.5s）——M2 出口判据首次在自动化验收里走通**，AGENTS §8 场景化全句的七要素全部被断言：真实管线采集 → 避开课表的可解释计划（learned:course 75 / default 双向）→ 超时 Focus（100 vs 计划 75）→ 引用超时分钟数的重排建议（worker cron 排水触发）→ L4 保护确认 → 接受即取代 → 带证据的 L1 记忆可修正（superseded-by 链）可拒绝。

## 环境（可复现）

- 独立库 `agenthu_e4`（alembic 从零 up 到 `f63b7e2a5c91`），API `uvicorn :8010`（`STORAGE_BACKEND=memory`），arq worker 同库同 Redis（`WorkerSettings` 3 functions + 30s cron）。
- 纯 API 账号（无构建包依赖）：E4 seed 走 `POST /v1/events/batch` → 派生 → Focus PATCH（actual 覆盖值）。
- Playwright：worktree `apps/desktop`，`AGENTHU_TEST_BACKEND_URL/EMAIL/PASSWORD` + `AGENTHU_E4_FULL=1`。

## 过程中的两次失败与修复（都有真价值）

1. **首轮 seed 全挂：任务停 `in_progress`、actual 丢失**。API 日志坐实两个叠加缺陷（PR #29）：
   - `memory_kind` 绑定漂移——`sa_enum` 按成员名绑定（EPISODE），`create_all` 测试库 CHECK 同名渲染所以全绿，迁移手写小写 CHECK 在真实库上拒绝写入；`alembic check` 不比对 CHECK 值列表，漂移不可见。修复：kind 列 `values_callable` 绑定小写值（不动共享 helper——focus status/audit 等存量表存的是大写名）。
   - 学习写入与任务完成共生死——同一 handler 的 savepoint 把状态更新一起回滚。修复：学习写入拆为独立 `focus.completed` handler（C1 语义各自 savepoint，学习失败只损失记忆行并审计）。
   - 回归封堵：`test_focus_learning_handler_on_migrated_schema` 在**纯迁移产物**上跑全链（create_all 盲区的永久检查）。
2. **全链首轮「90s 建议未出现」**：残留的旧代码 worker 进程（1 functions，#27 之前）抢着排水但无 cron——清场重启后触发引擎在真实栈闭环（建议 reason =「Focus 实际 100 分钟，达计划 75 分钟的 133%」）。教训入 README 口径：起 worker 后看一眼 `Starting worker for N functions`。

## 已知口径（沿用 PR #28 注记）

- worker 必须在（cron 排水驱动建议）；连续两轮全链 ≥30 分钟间隔（限频统计任意历史建议——本次以换新账号替代等待，限频的真实栈行为由单测覆盖、未做双跑实证，如实记录）。
- 建议**非深夜窗口**跑（budget 随墙钟收缩，深夜 today 计划诚实地为空）。

## 遗留

- 深夜空草稿翻搅的产品裁定（协调人移交 A）：**裁定方向 = 复用条件扩展**——「当日剩余预算不足以放置任何待办时，允许复用当日空草稿」（D-019/D7 reuse 条件的第三分支）：直接消灭 churn，深夜用户看到空计划 + 任务列表有待办 = 真实世界状态；「重生成时退休旧空草稿」为备选。立项为小 PR（planner `latest_open_plan` 条件 + 测试），不在 E4 已绿的 main 上连夜动 planner。
- PR #29 合并后 B 侧按 README 口径做一轮复跑（≥30 分钟间隔）作为双人确认。
