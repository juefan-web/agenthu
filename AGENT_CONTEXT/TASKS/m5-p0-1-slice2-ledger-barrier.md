# M5 P0-1 切片 2：持久操作/清理账本、owner 屏障与代际、依赖清单矩阵

Status: **实现中（2026-10-05 开工）**。基线 main `3f023ca`（#68 已合并）。
依据：[D-036](../DECISIONS.md) §8-8 实施令（P0-1 = 依赖清单、持久操作/清理
账本、屏障/代际、迁移回填）与 [A 稿](m5-data-lifecycle-ops-contract.md)
§1/§2/§4/§6 冻结文本；切片 1（统一 live 谓词）已落地。

## 0. 任务边界

| 项目 | 本次切片 |
| --- | --- |
| 目标 | 落 P0-3（删除/导出 API）所需的全部持久底座：独立操作账本（幂等键 + 代际快照，不随 users 行 CASCADE 丢失）、durable 清理项队列（Redis 仅唤醒、崩溃不丢对象）、owner 屏障与 data_generation 原语（raise/lock/check/release，含 FAILED 不解除规则与 5/30/120/300/900s 退避梯 + 24h 自动重试窗口）、机器可执行依赖清单矩阵（存在但未登记 → 检查失败） |
| 输入 | D-036 冻结裁定、A 稿 §1 数据族表/§2 并发规则/§4 幂等与账本/§6 恢复重放、bf02eeb→3f023ca 现行码位（worker/enqueue.py 孤儿集、models 全集） |
| 输出 | 新模型 `data_lifecycle.py`（3 表）+ users 加 `owner_handle`/`data_generation`、迁移+回填、`services/data_lifecycle.py` 原语、`services/data_registry.py` 矩阵与 fail-closed 审计、集成测试、本文档 |
| 负责范围 | backend 模型/迁移/服务/测试/依赖矩阵（含 Redis 键与对象存储条目；本地客户端条目按 B 稿登记为文档面） |
| 不负责范围 | /v1/data HTTP API、preview/confirm/delete handler、receipt 能力签发（P0-3）；入口/最终写入检查的全面接线（P0-3 按 A 稿 §2.3 清单落，本切片只交 `assert_writable` 原语）；删除抑制账本（随 P0-3）；孤儿集流改接 durable 队列（随 P0-3 清理执行器，本切片保证队列可承载其语义）；X-Data-Generation 头（随 P0-3，代际 bump 生产者到位才有意义） |
| 验收 | 账本对 users 行删除免疫（集成测试实证无 FK 丢失）；幂等键同输入同 operation；清理项 claim 无双领（SKIP LOCKED）+ 退避梯/24h 窗口/耗尽 FAILED；屏障 scope/target 匹配语义 + FAILED 不解除 + account 不自动解除；generation 单调递增 + 过期观测拒绝；`audit_inventory()` 对 ORM 全表/Redis `agenthu:*` 字面量零未登记（并自证 fail-closed：注入假表/假键必须失败）；迁移升降级往返 + autogenerate 零漂移；全量测试/静态检查绿（CI 同形命令） |

## 1. 设计要点（对照冻结条款）

1. **独立账本（A 稿 §4「不能因删除 users 行 CASCADE 丢掉；业务查询不得
   拿它恢复用户身份」）**：`data_operations`/`data_cleanup_items`/
   `data_barriers` 全部以 `owner_handle`（users 上的 uuid-hex 不透明句柄）
   键控，**无任何指向 users 的 FK**；表内不存 user_id/email，业务侧无法
   join 还原身份。`data_generation` 活值在 users 行（写者按认证用户快速
   读取），创建 operation 时快照入账本（A 稿 §6：恢复时抑制与代际从
   独立账本重放，不依赖 users 行）。
2. **幂等（A 稿 §4）**：UNIQUE(owner_handle, kind, client_request_id)；
   同键同输入返回同 operation，不同输入由服务层抛
   `IdempotencyConflict`（P0-3 映射 409）。
3. **清理项 durable（A 稿 §2.5「清理账本与关系删除同事务，Redis 仅
   唤醒，spop 后崩溃不能丢对象」）**：`data_cleanup_items` 是事实队列；
   claim 用 `FOR UPDATE SKIP LOCKED`（复用 M4 agent_runner 模式）；
   失败按冻结退避梯 5/30/120/300/900s 各配一档，自动重试总窗口 24h，
   耗尽转 FAILED 并留 last_error 摘要（SafeError 语义，无原文/key）。
4. **屏障规则（A 稿 §2.2）**：`raise_barrier` 与代际 bump、operation
   登记同事务；`lock_owner_barriers` 提供 confirm 事务的 owner 屏障行锁
   （SELECT … FOR UPDATE）；`assert_writable(user, scope, targets,
   observed_generation)` 是 P0-3 全面接线的入口/最终写入检查原语；
   `release_barrier` 仅接受 source/memory scope 且须 COMPLETED 证明，
   **FAILED 永不解除**、account 屏障不自动解除（目标抑制另账，随 P0-3）。
5. **依赖清单矩阵（A 稿 §1「机器可执行矩阵；存在但未登记检查失败」）**：
   `data_registry.py` 每条 = 键、存储（postgres/redis/object_storage/
   local_client）、owner 解析路径、内容字段（含 JSONB 路径）、分类
   （user_content/derived/credential/audit/ops）、处置语义（引用 A 稿
   数据族行）。`audit_inventory()` 三向核对：ORM 全表 ↔ postgres 条目、
   源码 `agenthu:*` Redis 字面量 ↔ redis 条目、注册表自引用有效性；
   集成测试断言零缺口并自证 fail-closed。

## 2. 实现记录

- **模型**（`backend/models/data_lifecycle.py`）：`data_operations`
  （幂等键 UNIQUE(owner_handle, kind, client_request_id)；version 供
  expected_version 重试；data_generation 为接受时快照；SafeError 三分解）、
  `data_cleanup_items`（UNIQUE(operation, resource_type, item_ref, action)；
  attempts/claimed_at/next_retry_at/last_error）、`data_barriers`
  （scope/target/state/raised_generation/operation_id）。三表仅以
  `owner_handle` 值键控，**无 users FK、无任何身份列**；表内 FK 仅指向
  账本自家（CASCADE/SET NULL 均在账本族内部，删 users 行不可能波及）。
- **users 扩展**：`owner_handle`（uuid-hex、唯一、Python 侧生成）与
  `data_generation`（int，server_default '1'）。owner_handle **不用
  server_default 生成表达式**——PG 目录会存规范化副本，alembic 文本比较
  永久假漂移（实测探针抓到）；改为迁移内显式回填（加可空列→UPDATE
  uuid-hex→置 NOT NULL→建唯一约束）。
- **原语**（`backend/services/data_lifecycle.py`）：
  `get_or_create_operation`（同键同 target 同 operation；不同 target 抛
  `IdempotencyConflict`）、`enqueue_cleanup_items`（同 operation 重复登记
  幂等 no-op）、`claim_cleanup_items`（`FOR UPDATE SKIP LOCKED`；到期 =
  PENDING 过退避门 ∨ CLAIMED 租约逾期自愈，认领即 attempts+1）、
  `complete/fail_cleanup_item`（退避梯 5/30/120/300/900s、24h 窗口、
  耗尽 FAILED 留 safe 摘要）、`bump_data_generation`（UPDATE…RETURNING
  原子递增）、`raise_barrier`/`lock_owner_barriers`（confirm 事务行锁）/
  `matching_barrier`（account 全拦；source/memory 按 target ids 交集）/
  `assert_writable`（P0-3 接线用入口+最终写入检查原语）/
  `release_barrier`（仅 source/memory + COMPLETED；FAILED 与 account
  拒绝解除，测试钉住）。
- **依赖矩阵**（`backend/services/data_registry.py`）：26 ORM 表全登记
  （owner 解析路径/内容字段/分类/处置语义逐条对照 A 稿 §1 数据族行）；
  Redis 两条业务键（trigger:dirty、storage:orphans）+ arq 库管键；
  对象存储 file blobs；本地客户端三条文档面（sqlite/localStorage/
  Stronghold，owner=P0-2/P0-4）。`audit_inventory()` 双向核对
  （表↔登记、源码 `agenthu:` 字面量↔登记，AST 扫描、排除注册表自身
  防自证）；`redis_literals_in_source` 把文档字符串里的键形字面量也算
  进扫描——fail-closed 宁可误报。

## 3. 验证证据（本地，2026-10-05）

- **新集成测试 25 例**（`tests/integration/test_data_lifecycle.py`）：
  handle/generation 默认与唯一、bump 单调、过期观测拒绝；幂等三例
  （同输入同 operation、异输入冲突、**代际快照不参与重放比较**）；
  **users 行删除后账本三表全存活**（含无 user_id/email 列的结构断言）；
  清理队列（登记去重、claim 独占、DONE 需 CLAIMED、退避梯全走完
  attempts=5→FAILED、24h 窗口提前 FAILED、租约逾期自愈）；屏障
  （account 全拦、source 按 target 交集、他 owner 不受影响、FAILED 不
  解除/COMPLETED 解除/二次解除拒绝/account 拒绝自动解除、行锁、
  assert_writable 含代际）；矩阵（clean、注假表必败、注假 Redis 字面量
  必败、stale 登记必败、登记字段完备性）。
- **全量**：378 passed / 1 skipped（S3 env），较 main 基线 +25。
- **静态**：`ruff check .` 与 `ruff format --check .`（CI 同形双命令）全
  绿——同形注记实践奏效：format --check 在本地当场拦下 registry 一处
  排版（未出仓即修）；pyright 0 错误。
- **迁移**（scratch 库 agenthu_mig_check2，验后已删；切片 1 遗留
  agenthu_mig_check 一并清理）：旧头造行→升级→回填实证（owner_handle
  32 hex、generation=1）；downgrade -1→upgrade 往返干净（format 前后各
  一轮）；`revision --autogenerate` 探针两轮均 0 op（零漂移）。
- **OpenAPI/契约**：61 路径数不变、openapi.json 零 diff、
  `check_contract_drift` 无漂移——本切片零 API 面变更，D-035 排序规则
  不触发（客户端零影响）。

## 5. 实现期判断（供 B 互审与协调人核验）

1. **幂等比较不含 data_generation**：A 稿 §4 "同输入返回同 operation"
   的"输入"解释为**客户端可见输入**（kind/client_request_id/target
   快照）。若把服务端观测的代际也算输入，同一删除在自身 confirm bump
   之后的重放（202 丢失场景的正典路径）会误报 409。代际语义由
   `assert_generation_current` 与屏障承担，快照仅存证。
2. **claim 租约 5 分钟**（`CLEANUP_CLAIM_LEASE`）：冻结文本给了退避梯
   与 24h 窗口，未定崩溃认领的租约时长；取 5min 对齐 M4 claim_run
   租约量级。P0-3 若有实测依据可单常量调整。
3. **enqueue 重复登记语义 = no-op 返回既有行**：A 稿 §2.5 要求"清理
   账本与关系删除同事务"，未显式定重复登记；按幂等 no-op 实现（同
   operation 重算闭包不炸唯一键）。

## 4. 对 E7 账面的影响

E7-2「durable 账本不丢」与 E7-6「DB 清理账本仍有 key；恢复继续同
operation，最多自动 5 次」自此有承载底座（数字不变，实现状态见本文档）；
E7-5 竞态面的入口接线仍待 P0-3。
