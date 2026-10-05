# M5 规划指导：Alpha 数据生命周期与运行加固

Status: **规划草案 r1，2026-10-05**。基线为 M4 收口 main
bf02eeb5906aa2732708ced8fe792ae41be96dd4。本文不构成新契约冻结或开工裁定；
双草互审、协调人采纳后才进入实现。里程碑范围以 D-030 和
[路线大纲 M5](../HANDOFF/2026-09-30-roadmap-outline.md) 为准。

## 0. 任务边界

| 项目 | 本次规划 |
| --- | --- |
| 目标 | 使 Study + Time 的 Event → Memory → Agent 闭环能在多用户 Alpha 中安全运行；用户能查看授权、导出与真正删除数据，开发者能追踪故障并恢复服务 |
| 输入 | M4 收口证据、D-030/032/033/034/035、M3 删除图、现行代码、M4 五项结转、开源实现对照 |
| 输出 | 本指导、phase-0 双草任务、A/B 契约初稿、E7 验收方案、状态与交接记录 |
| 负责范围 | 扫描基线、提出字段与状态机、排序切片、权限/数据边界、退出门槛 |
| 不负责范围 | 本轮产品代码、实际删除用户数据、清理共享栈、轮换真实密钥、代替 A/B 签认、发布内测 |
| 验收标准 | 每项结转有负责人/触发器/出口；双稿字段可交叉核对；删除/导出/恢复失败路径可测试；事实有来源，提案与已接受决策分开 |

## 1. 已核实的起点

- [#66](https://github.com/juefan-web/agenthu/pull/66) 已合并，main 收口 SHA
  为上述 bf02eeb；该 SHA 的 [CI](https://github.com/juefan-web/agenthu/actions/runs/37256514192)
  和 [Client checks](https://github.com/juefan-web/agenthu/actions/runs/37256514201)
  均 success。
- E6 六用例两轮绿及 B「账实相符、无未解释残差」来自仓库归档。
  本次未重跑 E6、未访问验收数据库；详见
  [核账报告](../HANDOFF/2026-10-05-b-e6-audit-report.md)。
- 计数口径：#50–#65 排除关闭未合的 #53，共 **15 个 merge**，
  含 #50 契约冻结；#51–#65 排除 #53 是 **14 个 merge**；#66 是收口归档。
- M4 已采用朴素 runner、D-034 授权/租约/幂等、D-035 原文搜索；
  Chat 搜索实际为 **pg_trgm + literal ILIKE**，不是旧 phase-0 中的 tsvector。
  M5 不以替换 Agent 框架作为开工前提。

## 2. 仓库扫描：复用点与必须补齐的边界

| 基线位置 | 可复用事实 | M5 缺口/处置 |
| --- | --- | --- |
| [files.py](../../backend/api/v1/files.py)、[enqueue.py](../../backend/worker/enqueue.py) | 先提交关系删除，再删对象；失败进入 Redis orphan set | DB 行已消失且 Redis 失效时，清理凭据可能丢失。改为同事务持久清理账本，Redis 只负责唤醒 |
| [memory.py](../../backend/api/v1/memory.py)、[memory_lifecycle.py](../../backend/services/memory_lifecycle.py) | 有来源、修正/拒绝、superseded-by 链 | DELETE 仅删行。删除替代行的 SET NULL 可能重新暴露旧版本；需要全链/失效/重算规则 |
| [memory_retrieval.py](../../backend/services/memory_retrieval.py)、[estimates.py](../../backend/services/estimates.py) | live/non-rejected 过滤、独立估时样本门槛 | 两路径未过滤 valid_to；只写 valid_to 不足以阻止再使用。冻结失效过滤语义，保留不同门槛 |
| [reference_invalidation.py](../../backend/services/reference_invalidation.py) | Chat 删除使 run/action basis 引用 source_deleted | 未覆盖 Event/Memory/file、Plan/PlanItem、回答与 mutation.response；标签不能代替清除派生内容 |
| [agent.py](../../backend/models/agent.py)、[material.py](../../backend/models/material.py) | run context 保存引用/校验和；回答有引用元组 | args/display/basis/result、回答 quote、历史确认缓存仍可能有用户内容，不能略过 |
| [deps.py](../../backend/api/deps.py)、[user.py](../../backend/models/user.py) | 认证检查用户存在且 is_active | 可复用账号停用门；worker/同步还需屏障与数据代际，旧 JWT 和队列不能恢复数据 |
| [queue.ts](../../apps/desktop/src/sync/queue.ts)、[lib.rs](../../apps/desktop/src-tauri/src/lib.rs)、[App.tsx](../../apps/desktop/src/App.tsx) | SQLite/localStorage 队列、Focus 草稿；退出会 queryClient.clear() | 队列/游标/草稿没有账号命名空间，损坏备份还保存原 payload。先隔离账号并清理副本，再接数据控制页 |
| [rate_limit.py](../../backend/core/rate_limit.py)、[logging.py](../../backend/core/logging.py)、[middleware.py](../../backend/middleware.py) | 进程内登录限流、request-id、审计 | 多进程限流、外部调用 trace、日志字段白名单待加固；异常栈/路径/extra 也要检查 |
| [permissions.py](../../backend/api/v1/permissions.py)、[agent_tools.py](../../backend/services/agent_tools.py) | grant 可查询/软撤销；notify 有 category 值匹配 | 创建仍是通用 dict/upsert；channel 未在 matcher 中值级比较，local_time_window 执行需裁定，不展示超出实际保证的授权 |

以上是 Alpha 规划输入，不改变 M4 已达成的出口判据。

## 3. 分阶段实施顺序（待采纳）

| 切片 | 主责/互审 | 前置 | 可交付出口 |
| --- | --- | --- | --- |
| P0-0 双草冻结 | A/B 各一、互审；协调人裁定 | 本规划 | [phase-0](m5-phase0-prereq-docs.md) 清单闭合、登记新 Decision |
| P0-1 生命周期地基 | A；B 核接口 | P0-0 | 依赖清单、持久操作/清理账本、删除屏障、恢复抑制记录、迁移与回填；旧 JSON 依赖缺失不得静默跳过 |
| P0-2 账号本地隔离 | B；A 核同步门 | P0-0，可与 P0-1 并行 | 按 backend origin + server user id 隔离队列/草稿；遗留无主队列隔离；本地删除不清另一账号 |
| P0-3 导出/删除执行 | A；B 核响应 | P0-1 | 同图导出、L2 预览确认、源失效/重算、批量清理、对象失败恢复；E7 API 故障注入通过 |
| P0-4 数据控制与 grant | B；A 核权限 | P0-2 + P0-3 接口 | 导出/删除/回执、本地残留提示、窄作用域 grant 面板、同意说明；重建 Windows 包验证 |
| P0-5 可观测与多进程 | A：Backend/worker/storage；B：campus/native | P0-1 trace 字段冻结 | HTTP/worker/run/外部调用 OTel、脱敏、共享限流、Redis 断供策略、多 worker 竞态验证 |
| P0-6 发布门与恢复 | A：部署/密钥/备份；B：许可/客户端包；双方核验 | 许可盘点可提前；演练依赖 P0-3/5 | 逐文件许可有结论、测试 key 撤销、新配置就绪、迁移/备份恢复及删除抑制重放通过 |
| P0-7 E7 联合验收 | A 执行留证、B 独立核账；协调人收口 | P0-1–6 | [E7](m5-e7-acceptance.md) 硬门通过；构建/执行 SHA/账面一致，main 双 CI 绿 |
| P1 测量评估 | A 检索/负载，B 轮询/打扰体验 | 稳定脱敏测量面 | 提交选择结论；无触发数据则保留现实现，明确复查日期 |

工期以冻结后的逐切片估算为准；旧 TECH_STACK 的“原 M4 一周”不作为 M5 承诺。
Android 数据采集/Inbox、Exercise/Life、Review 留在 D-030 后续里程碑。

## 4. 五项结转的闭环

| 输入 | 优先级/负责人 | 建议与验收 |
| --- | --- | --- |
| grant 面板 + 文案类别 | P0，B 主责/A 授权校验 | 先支持实际可执行的 notify.push/replan；明确渠道、到期、撤销、预算与 consent 区别。错误 category/channel、过期/撤销、执行竞态拒绝；见 B 稿 |
| HNSW/检索重做桶 | 测量门，A 主责/B UX 核验 | 脱敏语料 1k/10k/100k chunks + 每用户 1k/10k Chat；记录真实规模、EXPLAIN、p50/p95、过滤后 recall@10。建议在10并发下 p95>500ms 或 recall@10<0.9 才提交优化 ADR；阈值是提案，非性能结果。短 CJK 查询单列，不用 HNSW 替换原文搜索 |
| D-034 Revisit 两项 | P1，B 体验/A 负载 | 现 Chat 3s × 最多40次；测10/50活跃用户、后台暂停/重连、感知延迟和 GET 数。建议 p95感知>5s 或 polling 消耗>10% API请求预算时评估SSE并保留轮询兜底。daily_budget=3 暂保留，自愿Alpha一周抑制/忽略反馈后裁定；E6 budget=2不是默认值依据 |
| OneTHU BSL/LearnX | P0 发布门，B 主责/A 核构建 | copied file、来源SHA、许可/例外、适用主体、source/binary分发逐项核；OneTHU授权不自动覆盖Agenthu，未澄清不能宣布通过。public代码盘点立即开始，与二进制分发分别给结论 |
| 真实 key 轮换 | P0 发布门，A/有权限操作者 | 分dev/test/alpha，记录key id/时间/旧key撤销验证/最低额度，不记录值。无真实凭据就保持待操作者执行，不能以replay或测试key充证 |

## 5. 复用与架构取舍

开源对照见 [交接 §4](../HANDOFF/2026-10-05-m5-planning-verification.md)。
LangGraph 的 checkpoint 多表删除、Mem0 的强制作用域/循环批删可以参考，
但不能覆盖 Agenthu 的 Event/Task/Memory/对象/客户端图。
优先复用 SQLAlchemy、Arq、ObjectStorage、M4 租约与幂等；
OTel 使用标准 SDK/instrumentation，避免自造 trace 协议。
本轮仅研究与起草，无复制代码或新增依赖；后续直接复用源码需固定SHA、
记录修改、保留许可/NOTICE，并单列隔离与失败测试。

## 6. 裁定、兼容与完成标准

裁定点集中在 A 稿 §8；不预占 Decision 编号，不自动修改 D-032/033/034。
新增 API 增量发布，客户端经 capability 检查才显示；
旧 DELETE、旧 grant、数据代际兼容期一起冻结。
关新入口可以回滚发布；已接受删除继续清理，不能恢复旧库撤销用户删除。

M5 出口同时要求：同图导出/删除证明，检索/Memory/对象无受控在线残留，
断供/多worker/旧队列不复活，外部调用可追踪且不泄露原文，恢复不复活，
许可与密钥有证据，E7真机双轮+独立核账+收口SHA双CI。
离线设备、供应商与备份期限明确披露，不把在线删除写成所有设备即时擦除。
