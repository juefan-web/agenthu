# M1 活雷②：Focus 暂停时长计入实际耗时（方案 §0 先落字）

Status: **§0 已冻结（A 拟，2026-10-08；a/b 裁定同日落字——协调人
委托 A 拟、B 复审把关。B 复审 RC-1（completed 快照）已补，待转
approve）。B approve 后即开工。**病灶实测基线 main
`931324f`。

## 0. 边界（冻结候选）

**病灶（`backend/services/focus.py` 实测三处叠加）**：

1. RUNNING→PAUSED→RUNNING 在 `update_focus_session` 的 else 分支仅翻
   `focus.status`——无事件、无时间戳。模块 docstring 自称 "Every
   transition is driven by an Event"，暂停/恢复两条转换违反该声明。
2. `_complete` 默认 `actual_minutes = _elapsed_minutes(started_at,
   now)` = 起止墙钟差：暂停过夜后恢复 5 分钟再完成 ⇒ 十几小时计入
   任务实际耗时 ⇒ 污染 re-plan 偏差信号与学习记录（第一阶段验收
   面直接受污染）。
3. 若直接补发 focus.paused/resumed 事件，现有 dedupe key
   `focus-session:{id}:{verb}` 按会话+类型固定——第二次暂停会被
   去重吞掉，多轮暂停-恢复链断裂。

**修法（最小侵入，仅后端；桌面端零改动——UI 只发 status，显示读
服务端返回）**：

- 迁移加两列：`paused_at timestamptz null`（当前未闭合暂停段起点）、
  `accumulated_pause_seconds int not null default 0`（已闭合段累计）。
  内部列不入 client 契约（ClientFocusSession 不变，OpenAPI 无漂移，
  以 drift 实测为准）。
- RUNNING→PAUSED：`paused_at=now` + emit `focus.paused`，payload 携
  `accumulated_pause_seconds`（暂停时刻的已闭合累计；本段此刻未闭
  合、无时长可携）；PAUSED→RUNNING：`accumulated += now−paused_at`、
  `paused_at=null` + emit `focus.resumed`，payload 携 `pause_seconds`
  （刚闭合段时长）+ `accumulated_pause_seconds`（闭合后新累计）。
  快照与列值同一事务同源写入，不构成第二事实源。
- 事件 dedupe 改按转换序号：`focus-session:{id}:{verb}:{n}`，n = 该
  会话该类型已发生事件数（emit 时查询计数）；多轮同类型转换各有
  其键。并发同键竞态（双客户端同时 resume）落在 dedupe 上=正确面
  （本就是重复转换）。
- `_complete` 默认值 = elapsed −（accumulated + 未闭合暂停段），下限
  保持 `max(1, …)`；ABANDONED 同口径闭合（虽不产 actual_minutes，
  状态一致性保持）。PAUSED 直达 COMPLETED/ABANDONED 先闭合当前
  暂停段。`focus.completed` payload 在 `actual_minutes` 旁携
  `accumulated_pause_seconds`（完成时刻已闭合暂停总累计；直达路径
  先闭合的段计入；与列值同事务同源，规则同上条快照）——快照族
  paused/resumed/completed 三角一次定形。
- `payload.actual_minutes` 客户端显式覆盖保持（=用户修正面，与
  deviation_note 同语义；schema 已有界 0..10080）。

**不负责**：暂停 UI/交互变化；Focus 多会话并发策略（advisory lock
现状保持）；历史脏数据回填（历史 actual_minutes 不回改，如实留档）。

**验收**：①暂停 N 分钟不计入实际耗时（含过夜钟差例）；②多轮
暂停-恢复全计；③PAUSED 直达 COMPLETED/ABANDONED 闭合暂停段；
④同类型转换事件 dedupe 各自独立（两次 pause = 两条事件）；⑤
docstring 声明补真（每次转换有事件）；⑥迁移 + fixtures + 全量
测试 + ruff/pyright 绿；⑦paused/resumed/completed payload 快照断言
（多轮各段时长独立可读，completed 携完成时刻暂停总累计含直达闭合
段，单事件自解释）。

**已裁定项（2026-10-08 落字：协调人委托 A 拟，B 复审）**：

- a) **历史会话不标注可疑**。承重理由：暂停转换历史上从未落事件/
  时间戳（病灶 1 本身），"哪些历史行被污染"**不可判定**——无暂停
  会话的 actual＝墙钟本就正确，全量标注将误伤多数正确行，选择性
  标注又无信号可选。落法：迁移前历史值语义在 DECISIONS 记一行
  "actual_minutes＝含暂停的墙钟上界"；单行修正面沿用客户端
  actual_minutes 覆盖。零 schema 成本、不回改（与"不负责"一致）。
  附归属（B 复审确认项落字）：消费侧（estimates/偏差服务）加一行
  actual_minutes 语义注释归实现片；迁移前历史时长是否降权区别对
  待，未来另裁、不入本片。
- b) **payload 携带暂停快照**（规格已并入上方修法与验收⑦；B 复审
  RC-1 补齐 `focus.completed` 快照，paused/resumed/completed 三角
  齐全）。理由：paused/resumed 均为本片新增事件类型，一次定形免
  日后 payload 版本化；audit 单事件自解释、免回放列状态。
