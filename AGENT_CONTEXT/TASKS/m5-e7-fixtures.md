# M5-E7 准备期任务：harness + seed fixtures + verify queries（P0-7 前置）

Status: **工件切片（2026-10-06 开工，协调人派工"E7 准备期 GO"）；双轮执行
等 P0-5/P0-6（P0-7 门）**。依据 [E7 验收](m5-e7-acceptance.md) §1-4；
family 真相源 = `backend/services/data_registry.py`；栈模式沿 E6 先例
（独立库/门控/假件，见 [m4-b3-e6-exit](m4-b3-e6-exit.md) §4）。

## 0. 边界

- **目标**：E7 验收的机制面全部就位——确定性 seed、预登记 manifest、
  registry 驱动的 verify pack、门控驱动套件、E7 栈 runbook；两条参考
  驱动（E7-1 导出、E7-3 source 删除闭包）证明端到端形状。
- **输入**：E7 验收冻结文本；main `31e4743`（P0-1..3 全部落地的 API/
  worker/registry 面）；E6 栈与假件模式；pgvector/s3mock 既有镜像。
- **输出**：`tests/e7/` 包（conftest / markers / seed_spec / manifest /
  seed / verify / cases / README）；提交在库的 seed manifest JSON；
  E7 栈 runbook；冒烟证据（原始本地受控留存，脱敏汇总入本档）。
- **负责范围**：A（server 侧机制面）。
- **不负责范围**：双轮执行（P0-7）；E7-9 观测面（P0-5）；E7-10 恢复/
  许可门（P0-6）；Windows 客户端侧 evidence runner（P0-2/P0-4 面，本片
  仅预登记占位）；provider 假件（执行期复用 E6 `e6-replay.mjs` 接线）。
- **验收标准**：
  1. `audit_inventory` 绿——本片不新增产品存储族，机制面零 registry 变更。
  2. seed 可重建：同 spec 重复 seed 产生相同 manifest counts（rebuild 幂等）。
  3. verify baseline 绿：未操作的世界 = manifest before counts 全对 +
     V 对照不变 + marker 零泄漏。
  4. 参考驱动 E7-1 / E7-3 在真实栈（uvicorn + worker + PG + S3 + Redis）
     走通并产出证据文件。
  5. 六查绿；OpenAPI 零变更（纯测试/工具面，无 schema/API 改动）。
  6. 预登记纪律机制化：verify 的 expected 只读**提交在库的 manifest**，
     现场重算 expected 即违例——"跑完改预期凑绿"被构造性排除。

## 1. E7 栈（runbook 摘要；完整步骤见 tests/e7/README.md）

- **DB**：compose db 容器（pgvector/pg16）上独立库 `agenthu_e7`，
  alembic 从零 up（E6 先例 `agenthu_e6`）。
- **对象存储**：同 s3mock 实例，独立 bucket `agenthu-e7`。
- **Redis**：执行栈 = 独立容器（runbook 给出 `docker run` 行）；准备期
  冒烟允许既有 `agenthu-redis-1` 的 DB index 15（独立 keyspace，
  FLUSHDB 范围有界）。见裁定④。
- **进程**：uvicorn :8011 + arq worker（`backend.worker.settings`
  .WorkerSettings），env：`DATABASE_URL=...agenthu_e7`、
  `STORAGE_BACKEND=minio`、S3 指向 `agenthu-e7` bucket、
  `REDIS_URL=.../15`（或独立容器）、`SECRET_KEY=e7-stack-secret-not-
  for-production`；provider 假件 :9099（执行期接，冒烟不需模型调用）。
- **门控**：`AGENTHU_E7_STACK=1` + `AGENTHU_E7_BACKEND_URL` +
  `E7_DATABASE_URL` / `E7_REDIS_URL` / `E7_S3_*`。门未开时 conftest
  `collect_ignore` 整目录——常规 CI 收集零噪声、形态数字零变化。
- **证据**：`output/e7/<round>/<case>/`（.gitignore 新增该路径；原始
  证据本地受控留存），脱敏汇总入本档 §6。

## 2. 设计裁定（开工自裁，随 PR 待 B 核）

1. **harness 形态 = pytest 门控套件**（`tests/e7/`），非独立脚本包：
   真栈 HTTP 驱动（httpx 打 :8011）+ 直接 SQL/对象/Redis 证据双轨；
   复用 pytest runner/assert 人体工学；E6 门控先例同构
   （`AGENTHU_E6_UI=1` → `AGENTHU_E7_STACK=1`）。套件不负责起栈——
   起栈是 runbook（执行协议的一部分，E6 §4 同构）。
2. **manifest 真相源 = 提交在库的 JSON**：`seed_spec.py` 声明式规格
   （固定 UTC 锚点 + 确定性 marker）→ `manifest.py` 从 spec + registry
   派生 before counts / 依赖历史链 / 逐 case expected
   delete|redact|recompute|retain + 原因 → 产物提交在库。执行期 verify
   **只读该 JSON**：现场重新派生 expected 直接报错。这是 E7 §1
   "不得跑完改预期凑绿"的机制化。
3. **marker 方案**：每用户独立 token（`E7MARK-U-<n>` / `E7MARK-V-<n>`），
   同名内容异 owner 靠 token 区分（同名 shape + 异 token）；泄漏扫描 =
   U token 全域查（V 全部面 / ops 面 / 对象 / Redis / 导出包），token
   为合成串非真实 secret。
4. **Redis 隔离口径**：执行 = 独立容器；准备期冒烟 = 既有容器 DB 15。
   registry 的 `agenthu:` 字面量**不改**——改前缀与 fail-closed
   literal 扫描（data_registry.redis_literals_in_source）相抗，隔离靠
   实例/DB index 而非键前缀。
5. **对象版本**：s3mock 无版本化——manifest 对象面记 head/list 存在性
   检查；versioning 证据在执行期以真实对象存储口径补（runbook 注明，
   E7 §3 "对象head/list/version" 的 version 项延后到执行轮核）。
6. **embedding**：seed 直写 Vector(1536) 确定性伪随机向量（规格派生，
   非模型产物）；向量检查用 pgvector 距离探针（删后目标内容零召回）。
7. **case 驱动分期**：本片交 E7-1 / E7-3 参考驱动 + E7-9 / E7-10
   blocked-stub（`blocked_by` 元数据显式报告，非静默 skip）；其余 case
   驱动随执行切片落——manifest 已对其全量预登记 expected，执行切片
   只补驱动不补预期。
8. **墙钟**：seed 固定锚点 `2026-10-01T00:00:00Z` 起的确定性时间戳；
   验证断言对运行时钟免疫（计数/存在性/内容匹配）；涉 TTL/expiry 的
   用例用固定未来/过去锚点构造（E7 §4 锚定/免疫/守卫标注）。
9. **seed 直插而非走 API**：确定性优先——直插绕过派生副作用（handler
   重算、投影刷新），行结构与约束（partial unique live index、
   client_event_id 唯一、(user,source,upstream) 唯一）与真实写入完全
   一致；真实流（导出/删除/幂等）由 case 驱动走 HTTP。seed 不含
   data_* 生命周期族行（before=0）——预览/确认/回执/清理项全部由
   驱动经 API 产生，保证账本行来自真实路径。

## 3. seed spec 家族清单（U/V 镜像；同名 shape 异 token 异锚）

每用户（V 完全镜像，token/锚异）：

| 族 | 行数 | 依赖/历史链 |
| --- | --- | --- |
| events | 6 | e1/e2 anchored assignment（onethu, upstream `E7-?-asg-1/2`）；e3 assignment（L1 源）；e4 focus.finished；e5/e6 L2 源 |
| tasks | 3 | t1/t2 = e1/e2 锚定派生（source=onethu, source_upstream_id 同锚）；t3 独立 manual（无边） |
| task_events | 1 | t3↔e3 纯边关联（去相关存活用例素材） |
| focus_sessions | 1 | fs1 ↔ t1（deviation_note 含 token）；结果 = e4 |
| goals | 1 | 标题 token |
| memories | 5 | m1 L1（源 [e3]）；m2a L2 v1→superseded_by→m2b（修正历史链）；m2b L2 live（源 [e5,e6]，subject_key，embedding）；m3 用户原创 L2（无源，embedding）；m4 L3（embedding） |
| plans / plan_items | 1 / 2 | plan basis 引用 t1+e1；pi1 basis→t1，pi2 result 含 token |
| current_states | 1 | recent_state token；pending_task_ids=[t2] |
| file_objects | 2 | f1 讲义.pdf、f2 作业.pdf（与 V 同名）；storage_key uuid 方案 |
| material_chunks | 4 | f1×2 + f2×2，各含 embedding(1536) |
| material_answers | 1 | 引 chunk [c1,c2] + memory [m2b]；answer 含 token |
| chat_sessions / chat_messages | 2 / 4 | s1×2 条 + s2×2 条；s2 一条 deleted_at 软删（内容含 token） |
| agent_runs | 2 | r1 COMPLETED（context_snapshot/tool_calls/result token）；r2 FAILED |
| pending_actions / mutations | 1 / 1 | CONFIRMED 链：args/display/basis token + mutation.response token |
| permission_grants | 1 | replan L2 scope |
| grounding / model consents | 1 / 1 | course token / — |
| notification_preferences | 1 | Asia/Shanghai |
| audit_logs | 3 | path/ip(TEST-NET-3)/UA/details 各含 token；resource_id 引 t1 |
| 对象 | 2 blobs | 内容含 token（f1/f2） |
| Redis | 0 | **不 seed dirty 成员**——成员会唤醒 trigger 评估 cron，seeded deadline 相对墙钟在过去，planner 会非确定造 AgentRun 行；baseline 断言两用户均无成员（worker 自主造活即红） |
| data_* 生命周期族 | 0 | 驱动经 API 产生（裁定⑨） |

## 4. manifest schema（提交物 `tests/e7/manifest.json`）

```json
{
  "manifest_version": 1,
  "generated_from": "seed_spec.py + data_registry.py",
  "registry_graph_version": "<graph_version()>",
  "seed_anchor_utc": "2026-10-01T00:00:00Z",
  "marker_prefixes": ["E7MARK-U-", "E7MARK-V-"],
  "before_counts": {"U": {"events": 6, "...": "..."}, "V": {"...": "..."}},
  "dependency_chains": [{"family": "memories", "chain": "m2a --supersedes_id--> m2b", "...": "..."}],
  "case_expectations": {
    "E7-3a_delete_anchored_event": {
      "operations": ["source delete event e1 (U)"],
      "expected": {"U": {"events": {"delete": 1}, "tasks": {"delete": 1},
                         "focus_sessions": {"delete": 1}},
                   "V": "unchanged"},
      "reasons": {"tasks.delete": "anchored_derivation（锚定判据，暂态投影编辑随整删）"}
    }
  }
}
```

`case_expectations` 覆盖 E7-1..E7-10 全部可预登记项；blocked 项
（E7-9/E7-10 的观测/恢复面）标 `blocked_by: "P0-5"/"P0-6"`，预期仍在
（执行轮核），驱动后补。

## 5. verify pack 检查面（E7 §3 的机制化）

- **registry 计数**：POSTGRES 族逐表 owner 限定计数 vs manifest
  expected（owner 条件先于内容查找）；OPS 族按 owner_handle/无主口径。
- **JSONB/文本 marker 扫描**：registry content_fields 逐列 + 指定
  JSONB 子键（evidence/source_event_ids/basis/context_snapshot/args/
  display/result/mutation.response）扫 U token；chat 原文 ILIKE 全文。
- **向量探针**：material_chunks/memories 以 U token 关联向量做
  pgvector 近邻查询——删后零召回。
- **对象面**：bucket 逐 key head/list；导出 staging/包存在性。
- **Redis 面**：dirty set 成员、E7 DB（index/容器）逐 scan——不以
  Redis 空推断全部清理成功（账本行/对象面独立核）。
- **V 对照**：V 全族计数与抽样内容不变；允许保留的 U 项逐条列明原因
  （来自 manifest reasons，不得临场增删）。
- **报告**：逐检查 pass/fail + actual/expected JSON，写入证据目录；
  非绿即非零退出。

## 6. 冒烟记录（2026-10-06，A 机）

- **栈**：compose db/s3mock 既有容器 + 独立库 `agenthu_e7`（alembic 至
  c7a3f02d9e51 从零 up）+ 独立 bucket `agenthu-e7` + 既有 Redis DB15
  （裁定④冒烟口径）+ uvicorn :8011 + arq worker（env 见 README；
  `AUDIT_ENABLED=false` 确定性口径）。冒烟后栈已停，库与 bucket 留作
  B 核账（README §5）。
- **seed**：90 行 + 2 用户 + 2 blobs 全通（每表 flush 修复后）。
- **baseline**：全绿（before counts ×2 用户 ×30 族 + marker 双向隔离
  + 7 向量探针自最近邻 + 2 blob 存在性 + dirty 集空）。
- **门控套件**：`4 passed + 2 skipped`（E7-1 导出全链含包内扫描/
  include_files=false/所有权边界；E7-3a/b/c 三类 source 删除闭包 +
  verify 全绿；E7-9/10 blocked_by 显式 skip）。证据
  `output/e7/smoke/`（本地留存：operation/verify/package-scan JSON）。
- **冒烟钉住的六个事实**（已修入码，B 核点）：
  1. worker 自主造活两径必须规避：dirty 成员唤醒 trigger cron（seed
     不碰 Redis）；CONFIRMED pending action 会被 dispatcher 重派
     （seed 播 SUCCEEDED 终态，行仍属删除闭包全量内容）。
  2. task_events 无 id 列（关联表）；seed 按 FK 序逐表 flush（无
     relationship 的表对 unit-of-work 不排序，chat_messages 字典序
     先插会违约——最小复现已钉）。
  3. AgentRun 合法终态是 SUCCEEDED 非 COMPLETED；导出终态是 READY
     （staged+verified 待下载）——wait_operation 按 success_states
     分型接受，非成功态即诚实失败。
  4. 导出包是 deflate 压缩 zip——marker 断言必须扫解压后成员
     （初版扫原始字节全 miss，第一课）。
  5. 导出有意省略面（驱动显式清单带出处）：current_states 重建不
     导出（registry 原文）、audit 内容无关（§5：action/actor/time）、
     plan.basis 不随包；其余 U 内容全在场，V 零泄漏。
  6. material_answers 的删除闭包链是 `citations[].file_id`（非
     chunk_ids）——seed citations 补 file_id 后 E7-3b 绿。
- **生命周期族计数语义**（count_minimums）：data_operations/previews/
  barriers/suppressions/cleanup_items 的行数随 executor 相位扇出，
  精确钉行会把 manifest 耦合到实现细节；内容族保持精确 delta，生命
  周期族下限在场 + `cleanup_ledger_drained` 不变量（无 PENDING/CLAIMED
  残留）承载"durable 账本不丢"。
- **E7-3a 真实账**（修正后的预登记）：events/tasks/focus_sessions/
  current_states 各 -1（投影行随整删清，fence 负责后续重建）。

## 7. 实现期判断（待 B 核）

1. **audit 默认开**（config `audit_enabled: bool = True`）：E7 栈必须
   `AUDIT_ENABLED=false`，否则每次 API 调用写审计行破坏确定性计数；
   seed 直插的审计行足以证 §5 脱敏（account 删除后 ip/ua/path/details
   由 marker absence 核）。若 B 认为执行轮需要开 audit 跑 E7-5，用例
   期望须改为 audit 下限语义（同 count_minimums 理由）。
2. **baseline 合同 = seed→baseline 顺序**：baseline 校验"未操作世界"，
   必须紧跟 seed 跑；跑在用例残世界上会如实红（冒烟末轮演示过一次，
   重 seed 后复绿）——这是口径不是缺陷。
3. **exports_exact 与桶龄**：fresh world 的桶清空（整桶 purge + 重放
   blob）是对象面确定性的前提；staged 包跨用例累积会污染精确计数
   （初版 actual=9 的教训）。
4. **marker 粒度=字符串级**：一行共享的 marker 串在另一行属保留内容
   时会让 absence 断言失明（e4.task_title 初版复用 t1.title 串）；
   seed 纪律=每个内容位独立 marker，manifest marker_inventory 即审
   计面。
5. **E7-2..E7-8 驱动面**：manifest 已全量预登记；驱动随执行切片落，
   预期不再动（除非产品面语义变更，届时 manifest 重生 + B 重核）。
6. **Redis DB15 冒烟口径的边界**：arq 在 DB15 写队列/结果键（库托管
   键族）；执行轮独立容器（README §1）后该口径作废，验收记录必须
   用独立容器的 REDIS_URL。
