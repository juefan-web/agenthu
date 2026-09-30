# M2 任务分解（依据 2026-09-30 实现评估）

上游输入：`HANDOFF/2026-09-30-implementation-evaluation.md`（概念对照 + §3
实现路线，事实断言已经协调人逐项核验属实）。**M2 出口判据 = 评估报告末节的
场景化 AGENTS §8 全句**：真实账号采集 → 得到避开课表、每项有人话理由的计划
→ 完成一次超时的 Focus → 收到引用超时的重规划建议并接受 → 看到带证据、
可修正/可删除的 L1 学习记忆——全部过 e2e。

## 冻结先行（阶段 0，A 产出、B 评审）

1. `PlanItemSchema.basis`（optional 结构化理由对象）+ `recent_state`
   （`z.record(z.unknown())`）入契约——drift 基线同步。
2. Memory 模型扩展（评估 §3.4 五项：`subject_key`/版本字段/`kind`/`evidence`
   /embedding 预留）——迁移 + fixtures + OpenAPI。
3. 重规划建议的契约形状（`replaces_plan_id`、`replan_reason`、Level 1 语义）。
4. 「LLM/Agent 推迟至 §3.1-3.4 闭环之后」补正式决策条目（评估指出的
   静默漂移）。

> **产出（2026-09-30，A）**：第 1–3 项冻结为 **D-031**（另冻结估时来源
> `estimate_source` 语义，E4 断言依赖）；第 4 项已由 **D-030 第 2 点**覆盖。
> E4 场景草案与 **fixture 冷启动注意**（估时 learned 路径需预置带 actual
> 的同课程完成任务）见 `TASKS/m2-phase0-contract-freeze.md`；Memory 迁移
> 全案（含删除/依赖图）见 `TASKS/m3-memory-schema-migration.md`。

## 开发者 A（Backend / 数据平台）

1. **Planner v2**（评估 §3.1）：槽位式（复用 `_today_schedule_entries` 单一
   课表源 + 通勤缓冲）、总量对齐 `available_minutes`、确定性打分
   （slack + goal + priority）、>90 分钟拆块、负 slack 标 at-risk（Deadline
   Radar 种子）、`strategy="slots_v2"` 版本标签（同 fixture 可对比评估）。
2. **结构化 reason**：per-item basis（deadline/slack/estimate_source/slot_reason
   /score 分量）+ 中文模板渲染（例句见评估 §3.1）。
3. **批次重算优化**（评估 #4）：handler 标脏、批末一次 recompute；投影哈希
   不变跳过 version bump。
4. **Memory 管道**（评估 §3.4）：L1 episode 由 `focus.completed` handler 直写
   （含 `deviation_note`，证据指向 focus/task 事件）；`subject_key` upsert、
   REJECTED 阻断再派生、CORRECTED 走 supersedes；检索带置信度下限。
5. **估时学习**（评估 §3.2）：课程先验中位数 + 用户校准比，**存 L2 Memory
   行**（可溯源可修正），置信度 `min(0.9, n/10)`，低于阈值回退默认并在
   `estimate_source` 声明。
6. **Worker 首批真实任务**（评估 #12）：去抖 recompute + 重规划触发器评估
   （§3.3 五类触发，30s 去抖、30 分钟限频、deadline at-risk 豁免）。
   重规划**只建 DRAFT**（`replaces_plan_id`），绝不改已确认计划。
7. 顺带小修：哨兵 updated 事件清空既有任务 deadline（评估 #11）；
   逾期任务分桶策略（#3）。

## 开发者 B（Client / 闭环呈现）

1. **计划理由呈现**：`reason` 人话渲染 + 可选 `basis` 结构化展示（why 面板
   雏形）。
2. **重规划建议 UI**：diff（移动/新增/丢弃）+ 接受（走既有 confirm 路径）/
   忽略；限频下的安静态。
3. **Memory 页面**：每条记忆带证据，可确认/修正/删除——「可修正」这半句
   验收的落点。
4. **App.tsx 拆分**（评估 #15）：feature 目录 + 上下文注入单例，为上述三个
   新 UI 面腾出可测试的结构。
5. 小项：e2e 两处健壮性修订（首跑报告）；断网快速失败（#9，/health 探测
   ≤2s）；D-029 落地时的 `x-next-cursor` 代理白名单（#8，一行）与客户端
   游标循环消费。

## 顺序与纪律

- 3.1→3.2→3.3 依赖链明确，全部**无 LLM**；§3.5/3.6（资料/Agent）在 M2 出口
  判据通过前不动。
- 新域（Inbox/Life/Exercise）继续冻结（评估 §3.8：vendored core 现成的
  接口每个都是「一个适配方法 → 一个事件类型」，等闭环学会再加）。
- 验收：e2e 先行（E1-E3 + 新增 M2 判据 spec），人工聚焦故障注入。
