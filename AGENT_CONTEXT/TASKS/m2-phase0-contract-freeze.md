# M2 阶段 0：契约冻结产出与 E4 出口场景（A 产出、B 评审，评审窗口半天）

上游输入：`TASKS/m2-breakdown.md`（冻结先行四项）、
`HANDOFF/2026-09-30-implementation-evaluation.md`（§3.1–§3.4）、
`HANDOFF/2026-09-30-roadmap-outline.md`（M2 节，D-030 已采纳）。

## 冻结产出对照

| m2-breakdown 冻结项 | 落点 |
| --- | --- |
| 1. `PlanItemSchema.basis`（optional）+ `recent_state` 入契约 | **D-031 §1**（recent_state 语义本就在 D-027 附录，此处仅排期） |
| 2. Memory 模型五项扩展的迁移方案 | **D-031 §3**（形状与切片）+ `TASKS/m3-memory-schema-migration.md`（迁移步骤、写入者语义、**删除/依赖图**——D-030 修订要求） |
| 3. 重规划建议契约形状（`replaces_plan_id` / Level 1 语义） | **D-031 §2**（零迁移；接受即取代是唯一新行为规则） |
| 4. LLM/Agent 推迟补正式决策条目 | **已由 D-030 第 2 点覆盖**（2026-09-30 采纳），不另立条目 |

另冻结估时来源语义（`estimate_source` 取值、分组键、激活阈值与采用阶梯，
D-031 §4）——它不是客户端契约字段，但 E4 的断言和 B 的 basis 面板都消费它，
不先冻结会直接撞上 E4 编写。

评审通过（D-031 转 accepted）后，双方即按 `m2-breakdown.md` 的 A/B 清单并行；
A 侧首批迁移：`plan_items.basis` + memories 六列（M2 切片），随后 OpenAPI /
drift 基线 / fixtures 同步一次完成（D-031 §5 清单）。

## E4 出口场景草案（M2 判据 spec，B 落地为 e2e）

> 对应评估报告末节的场景化 AGENTS §8 全句。E1–E3 已绿（首跑报告），
> E4 是新增 spec；以下步骤供 B 写 spec 与 A 写服务端回归测试共用。

1. **预置（seed，全部走真实 API，不直写 DB）**：
   - 经 `POST /v1/events` 上报 `study.assignment.discovered` ×3（+08:00
     deadline）：同课程 X 两份（作业 A/B，不同 `upstream_id`）、对照课程 Y
     一份（作业 C）。
   - 对 A、B 两个派生任务各执行一次 Focus 并完成（`planned_minutes` 语境下
     actual 分别为 60 与 90）→ 任务 COMPLETED、`actual_duration_minutes`
     落库。
   - 当日课表含一节下午课（`time.schedule.entry` 事件或既有采集）。
2. **生成与断言（计划 v2）**：`GET /v1/plans/today` → 断言 (a) 无计划项与
   课表区间重叠（含缓冲）；(b) 每项 `reason` 是人话（不含
   `deadline_then_priority`/`slots_v2` 等内部标识符）；(c) 课程 X 任务
   `basis.estimate_source == "learned:course"` 且 `estimate_minutes != 60`
   （seed 60/90 → 中位数 75）；(d) 对照课程 Y 任务
   `estimate_source == "default"`。
3. **超时 Focus**：对计划中课程 X 的一项执行 Focus，超时完成（planned 75 →
   actual ≥ 1.3×，如 100 分钟），填 `deviation_note`。
4. **重排建议出现**：断言 `GET /v1/plans?status=DRAFT` 存在
   `replaces_plan_id` 非空的草稿；`replan_reason` 引用超时事实（含实际分钟
   数）；被替代计划**仍为 CONFIRMED**（L4 保护）。
5. **接受**：`POST /v1/plans/{id}/confirm` 建议草稿 → 断言新计划 CONFIRMED、
   被替代计划 SUPERSEDED（接受即取代，D-031 §2）。
6. **L1 记忆与可修正**：`GET /v1/memory` 出现本次 focus 的 L1 episode
   （kind=episode、evidence 含 `focus.completed` 事件 id 与任务派生事件 id、
   `deviation_note` 入内容）；修正（→ CORRECTED 新版本，旧行被 supersede、
   不原地改写）→ 删除（DELETE）→ 列表不见。**「可修正/可删除」半句在此闭环。**

### ⚠ E4 fixture 冷启动注意（评估 §3.2 的落地坑，先写进 spec 再写代码）

**估时学习的 `learned` 路径需要历史 actual。** 若 E4 从零账号冷启动，生成
受验计划时同课程完成数恒为 0，`estimate_source` 只会是 `default`——「学习」
从未发生，E4 恰恰没有证明它要证明的东西，而且失败是**静默的**（计划照样
生成、照样避开课表，spec 不主动断言就全绿）。

- seed 必须在**生成受验计划之前**完成（上文步骤 1），并让「学习」路径真实
  跑过一次：两个 seed actual 取不同值（60/90 → 中位 75，避开取整边角）。
- 断言双向：`learned:course`（有历史）与 `default`（无历史对照）同时断言
  ——只断前者无法证明「如实标注」，只断后者连学习路径都没执行。
- seed 用**派生任务**而非手动任务：估时分组键是 `task.extra.course_name`
  （D-031 §4），手动任务没有课程身份，走 events → 派生 → focus 的真实管线
  才是诚实路径（顺带覆盖派生幂等与 focus 完成累计）。
- n≥2 阈值（D-031 §4）与 seed 数量对齐：两个 seed 恰好激活 `learned:course`；
  若后续把阈值调高，E4 seed 数量必须同步（spec 里写死 seed 数并注释阈值）。

## 验收标准

- B：D-031 评审意见回录（approve 或修改裁定）；E4 spec 按 D-031 §2/§4 与
  本文件草案落地，含冷启动 seed 与双向 estimate_source 断言。
- A：D-031 转 accepted 后，迁移与契约同步按 §5 清单一次完成；服务端回归
  覆盖接受即取代、REJECTED 阻断、CORRECTED 版本链、估时阶梯四分支。
- 共同：E4 在真实账号全绿 = M2 出口判据达成（D-030 第 2 点）。

## 不负责范围

M3 资料摄取与 grounding、Agent runtime（新 M4）、Android/Inbox、录音转写
（隐私决策后置项）。本文档只冻结 M2 契约与出口场景，不实现代码。
