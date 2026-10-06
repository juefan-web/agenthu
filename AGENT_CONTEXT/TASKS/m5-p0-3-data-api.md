# M5 P0-3：删除/导出 API 与执行（A）

Status: 开工 2026-10-05；基线 main `824ab5a`（#70 合并头）。
依据：D-036（含 §8 实施令与参数裁定）、
A 稿 `m5-data-lifecycle-ops-contract.md`（冻结 r2）§2-§4、
B 对 #70 的 head-bound 互审（approve；携带项三 + should-fix 一 + advisory 一）。

## 0. 边界

- **负责**：/v1/data HTTP 面（capabilities / previews / deletions / exports /
  operations/{id} / download / retry / receipts/{id} / deletions/recover）、
  preview 图闭包计算与 10min 摘要绑定、confirm 事务（复核 + 屏障锁 +
  清理项登记 + data_generation bump + 抑制标识 + receipt 能力签发）、
  执行 worker（export 三 phase / delete 四 phase + 退避梯 + verify）、
  `assert_writable` 按 A 稿 §2.3 清单全面接线、X-Data-Generation、
  孤儿集流（storage orphans）改接 durable 队列、N1/N2 携带。
- **不负责**：数据控制页 UI 与 grant 目录（P0-4，B）、E7 执行与 seed
  fixtures（独立验收）、备份/恢复演练（E7-10）、校园 connector 变更、
  Stronghold 本机清理（B 稿域）。

## 1. 强制携带清单（协调人裁定 + B 互审产出；协调人在本片验收核对）

1. **IntegrityError 收敛**（B 携带①，#70 互审）：首次确认时 owner 无
   屏障行 → `lock_owner_barriers` 空集无锁可加 → 同 key 并发 confirm 双
   SELECT 不见对方 → 双 INSERT，一发死于 `uq_data_operations_idem`。
   confirm handler 必须捕获 IntegrityError → 重查 → 比对 → 收敛为"返回
   同 operation"（或以 bump 的 users 行 UPDATE 锁先行串行化）。随 confirm
   handler 落地并配并发测试。
2. **memories.content_fields 补 `embedding`**（B should-fix）：handler 按
   字段清单清洗，向量残留恰是 E7-4 要抓的形状——已随本片首提交落。
3. **`matching_barrier` 对 `target_ids=None` fail-open 收口**（B 携带②）：
   已硬化为同 scope 屏障 + 未指明目标 = 冲突（fail-closed，首提交落，
   测试钉住）；接线纪律（scoped 写必传 ids）随 §2.3 接线切片执行，
   account 屏障语义不变。
4. **N1**（#68 B 注记，B 原文）：`_require_live` 只查指针；删除切片引入
   valid_to 退休后，correct-on-retired 会以新活行复活被生命周期退休的
   内容（E7-3/E7-7 形状）——已升级为全谓词（首提交落，测试钉住
   retired/future 两向 + live 基线）。
   **N2**（记档项，无代码）：downgrade 在含"退役解指针行 + 同 key 新活行"
   的数据上会响亮失败（宽化索引固有，零基 CI 测不出）；删除纪元后的
   迁移回滚须先手工对账此形状，E7-10 恢复演练覆盖。N3（未来 valid_to
   writer 的唯一性回退）维持档位：有界有效期窗口 writer 到来时随设计
   携带，本片不产生该 writer。
5. **DECISIONS 实现注记**（B 已核论证）：owner_handle 显式回填 vs 表达式型
   server_default 的 PG 目录规范化假漂移范式——已随本片落 DECISIONS。
6. **enums 名=值对齐**（B advisory，A 裁量 = 采纳）：SAEnum 持久化名、
   CHECK 按名生成，值对齐名不动 DB 任何字节（零迁移）；模块 docstring
   的 JSON 往返稳定契约恢复。已随首提交落（4 个新枚举：Kind/Phase/
   CleanupItemAction/BarrierScope；其余 3 个本已对齐）。
7. **"connector 事件必须带 upstream_id" 前置纪律**（协调人切片 3
   强携，源自 #72 互审）：抑制拦截与 E7-7 重采 seed 均锚
   provenance.upstream_id——无锚事件既不可抑制也不可重采追踪。本片
   入口不做 422 强制（manual/test 源合法无锚，见 §2B-5/§5-10）；
   纪律落 P0-6 connector 适配层（入队前断言），真 connector 落地时
   该断言是硬门。E7-7 重采 seed 用带 upstream_id 事件（#71 账面
   无需改，E7 行已记）。

## 2. 切片计划

- **切片 1（本 PR）**：首提交（任务书 + §1.2/3/4/6 + DECISIONS + 本文档）
  + DeleteTarget/preview 服务（闭包枚举、effects 计数、digest、10min
  有效）+ confirm 事务（幂等、409 语义、屏障、清理项、代际、抑制标识、
  account 删除 is_active=false + 撤 grant/consent + receipt 能力签发与
  摘要持久化、IntegrityError 收敛）+ HTTP：capabilities / previews /
  deletions / operations/{id}（含 SafeError/progress DTO 与 X-Data-Generation
  响应头）。
- **切片 2**：执行 worker（delete 四 phase 逐清理项执行 + 退避梯/租约 +
  verify 区分确证 404/403/网络故障 + RETRY_WAIT/FAILED 结算 + 屏障释放
  规则）+ exports 全链（collect/package/verify、staging 24h、manifest、
  include_files、download no-store、并发删除作废）+ retry（expected_version）
  + recover（digest 二因子、防枚举、限流）+ receipts GET。
- **切片 3**：`assert_writable` 全面接线（§2.3 清单逐点：新写入/context/
  dispatch/extract/embed/backfill/Focus/投影的入口与最终写入前、外部调用
  返回后复查；scoped 写传 ids 纪律）+ X-Data-Generation 入口检查 +
  孤儿集流改接 durable 队列（Redis 仅唤醒）+ source 抑制解除（重新授权
  路径）+ E7 账面随实现修订。

## 2A. 切片 2 开工裁定（2026-10-06，协调人令：先裁定后动 executor）

### 裁定①：多事件派生 task 的部分源删除语义

**依据**（均已冻结，非新裁量）：A 稿 §1 Event/Task/Focus 行"源删除区分
纯派生与独立用户编辑；派生内容清除，独立内容去相关来源后保留，preview
告知"；registry tasks 条目 disposal 同义。本裁定把"纯派生 vs 独立"操作化
为**锚定判据**：

1. **纯派生 = D-028 锚定**：`task.(source, source_upstream_id)` 匹配某被删
   event 的 `(source, provenance.upstream_id)`。D-028 派生 task 是上游
   assignment 的连续投影——title/description/deadline/extra 由每次
   assignment 事件整体重写（event_handlers.handle_assignment_event），
   不存在稳定的独立编辑面；状态（COMPLETED sticky）、Focus 实际耗时、
   计划条目结果都在 task 本体之外留痕。处置：**整删**；其
   focus_sessions 经 FK CASCADE 一并入闭包显式枚举（用户活动记录随
   派生对象消亡，preview 计数可见）；plan_items.task_id 经 FK SET NULL
   **存活**（计划历史是用户工作成果，actual_minutes/result 留在条目上），
   title 拷贝残留记入 limitations、basis 失效由重算处理。
2. **相关但非派生 = 用户关联**：task_events 边连到被删 event 但锚不匹配
   （手工 task、锚在其它 event 的 task）。边是用户手工建立的相关性记录
   （api/v1/tasks.py 206/218），不是内容拷贝。处置：**去相关存活**——
   边行随 event 行删除经 FK CASCADE 消失，task 本体保留；闭包把边列为
   delete_ids（reason_code=decorrelated），VERIFY 覆盖边。
3. **切片 1 双向修正**：切片 1 闭包经 task_events 边 join 拉 task——
   对冻结语义**过删**（用户关联的手工 task 被整删）且**漏删**（D-028
   锚定但无边的 task 带着复制内容存活）。裁定后闭包改按锚查询为主、
   边仅产生去相关效果。
4. **preview 区分**（B 核点）：tasks 家族 reason_code=
   `anchored_derivation`（整删）；task_events 家族 reason_code=
   `decorrelated`（去相关）；focus_sessions 级联入 effects；
   plan_items SET NULL + basis 重算记 limitations。E7-3 预期账面同步。

### 裁定②：executor 分派纪律（先读 payload 再分派）

DELETE_RELATIONAL 项 executor **先读 payload 再分派**：
`payload.redact is True` → audit 脱敏路径（UPDATE 置空
details/path/resource_id/ip_address/user_agent，不删行，90d 回执保留）；
否则 → 行删路径（DELETE WHERE id IN payload.ids；task_events 用
(task_id,event_id) 对判别）。错路由=把 redact 当行删执行，方向上是
隐私安全的损失但违背回执保留语义——**单元测试 + 集成测试双钉红**。
配套：account 闭包的 audit redact_ids 从 `audit:{index}` 占位改为**真实
行 id**（占位符让 executor 无从定位行；redact 计数语义不变）。

## 2B. 切片 3 范围裁定（2026-10-06，A 开工自裁；冻结文本出处随项标注）

1. **接线面**（A 稿 §2.3 清单逐点）：统一走 `services/write_guards.py`
   门面（assert_write_allowed / is_suppressed / release_source_suppressions /
   current_generation_of），业务路径不直接摸 data_lifecycle 原语——
   WriteBlocked/SuppressedSource 都是 ConflictError 子类带 scope，HTTP
   409 语义与 worker §2.4 结算码共用一个来源。
2. **§2.4 终态落点**：run 入口（claim 后）与两次 provider 写回点查
   屏障 + 代际 → **CANCELLED + failure{account_deleted|source_deleted}**，
   不写旧结果、不写 assistant 消息；action 入口（§2.4 CONFIRMED/
   FAILED_RETRYABLE 用 FAILED——CONFIRMED 不伪称过期）与工具执行后
   同查 → FAILED + last_error.code；已发外部请求不声称撤回（文案保留
   "side effects not claimed revoked"）。
3. **投影豁免 source/memory、只跳 account**：flush_state_recompute 对
   account 屏障 skip（executor fence 拥有闭包后投影，fresh derive 是
   死行上的白工）；source/memory 不拦——投影非 id 分区，闭包后
   fence/recompute 周期收敛它。
4. **scoped 写传 ids 纪律**（B 携带③接线半）：chat=message 的 session id；
   memory create=引用的 event/evidence ids（SOURCE）+ lifecycle 内
   memory 行 id（MEMORY）；extraction/embed=file id。屏障 target 身份
   空间 = DeleteTarget.ids（切片 1 冻结），不发明第二空间。
5. **抑制锚 = provenance.upstream_id**（与登记同序，回落 event id 仅
   在登记侧存在——新事件无从知晓已删行 id，故拦截只匹配 upstream_id；
   无 upstream_id 事件照过，"connector 事件必带 upstream_id" 是
   connector 侧前置纪律，见 §3，不由入口 422 强制）。
6. **解除路径无 HTTP 路由**（A 稿 §4 冻结矩阵无此面）：释放走服务层
   release_source_suppressions（幂等 UPDATE released_at + audit 无内容
   行），触发面随 P0-6 connector 重授权流；不为它破 §4 冻结。
7. **孤儿账本**（A 稿 §2.5 / r2 补己见⑤三码位）：新表
   storage_orphan_keys（owner 无列——key 内嵌 uuid 可经 file_objects
   解析；state 复用 data_cleanup_state 枚举零新 PG 类型；成功即删行，
   outbox 式）+ 迁移 c7a3f02d9e51。files DELETE 在行删同事务
   register（崩溃后必有可领标记）、成功内联 release；drain cron 从
   DB 领取（FOR UPDATE SKIP LOCKED + 同 5/30/120/300/900 梯 + 5min
   租约），Redis 完全退出该流；enqueue.py 的 SADD/SPOP 对删除。
8. **account 闭包补抑制行**：data_suppressions 随账号终结（A 稿 §5
   保留期表"到重新授权/账号删除"）；receipts/operations/barriers/
   cleanup-items **不入闭包**（receipt 90d 窗口 + 本操作自身账本必须
   活过执行）。executor RESOURCE_MODELS 补 data_suppressions。



- **首提交（2026-10-05）**：§1.2 embedding 补录、§1.3 matching_barrier
  fail-closed（同 scope + None = 冲突；异 scope 不受影响）、§1.4 N1 全谓词
  （retired/future 双向拒绝，live 基线不回归）、§1.6 enums 名=值对齐
  （零迁移：SAEnum 持久化名，CHECK 按名生成，值改大写名不动 DB）、
  §1.5 DECISIONS 回填范式注记、本任务书（含 N2/N3 档位记录）。

- **切片 1 主体（2026-10-05）**：
  - **DTO**（schemas/data.py）：DeleteTarget 判别联合（account/source/
    memory；`include_history: Literal[True]`、`confirmed: Literal[True]`
    把"必须显式"压进类型）；错误组件命名 **DataSafeError**（与 agent 域
    既有 SafeError `{code,message}` 撞名，FastAPI 会模块前缀化——改名而非
    扩旧面，线上 JSON 形状即冻结文本的 SafeError）。
  - **闭包枚举**（services/data_closure.py）：preview/confirm/清理项共
    用一图。source/event → events + task_events 边 join tasks + Python 侧
    source_event_ids 交集（memories）+ current_states recompute；
    source/file → file_objects + material_chunks(file_id) +
    material_answers(citations 引用扫描) + 对象键；chat_session →
    会话+消息；chat_message → 消息本体；memory → supersedes 双向定点
    迭代整链；account → registry 全族扫描（含 plan_items/mutations 经
    join 的间接族、task_events 边、audit redact 计数、全部对象键）。
    所有权先于内容：目标 id 缺失/异主一律 404。版本戳：一律 updated_at，
    唯 ChatMessage 用 created_at（不可变行，无 updated_at）。
  - **preview**（data_operations.create_preview）：10min TTL + 惰性清除；
    digest 绑 user + target + graph_version（REGISTRY 内容 sha256[:16]，
    自维护）+ data_generation + 影响集 + 逐行内容版本——不是行数哈希。
  - **confirm 事务**（confirm_deletion）顺序：幂等重放优先（preview 行
    已过期/已清也返回同 op）→ preview 行/摘要 → 闭包重算比对（漂移=
    409 preview_stale，不静默扩大）→ 同 scope 在途屏障（409
    deletion_in_progress）→ **bump 代际（users 行 UPDATE 锁 = 并发同 key
    confirm 的串行化点，携带①）**→ 锁内幂等复查 → savepoint 内 INSERT
    （IntegrityError → 重查收敛同 op / 异输入 409，携带①双保险）→
    屏障升起 → account：is_active=false + grant/consent 撤销时间戳 +
    receipt 能力（token_urlsafe(32)，账本只存 sha256 摘要，202 响应仅
    一次吐出）/ source：抑制行（HMAC-SHA256(secret_key, kind:upstream)，
    events 用 provenance.upstream_id、缺失回落 event id；file/chat 用
    行 id）→ 清理项登记（DELETE_RELATIONAL 携 payload ids / account 全
    域无 payload、DELETE_OBJECT 逐对象键、CLEAR_REDIS 仅 account、
    VERIFY_ABSENT 逐族）→ progress_total/outstanding 落值。
  - **迁移 a9c41f7d2e83**：data_previews（users FK CASCADE——瞬态非账本）
    + data_receipts/data_suppressions（owner_handle 值键控无 FK——必须
    活过 users 行删除）+ data_operations.preview_digest/impact +
    data_cleanup_items.payload。
  - **registry**：三张新表登记（inventory 在开发期即抓到未登记——
    fail-closed 自证一次）+ graph_version()。
  - **路由**（api/v1/data.py）：capabilities（export_enabled=false 诚实
    不广告未落地面）/previews 201/deletions 202/operations GET +
    X-Data-Generation 响应头。账号删除后 is_active=false → 业务 auth
    即 401（deps.get_current_user 既有语义），停用后读取走 receipt
    路径（切片 2）。

- **评审修订（2026-10-06，B RC 唯一必改项）**：补"过期 preview ×
  幂等命中 → 同 op"组合测试（核点 4——冻结句"删除重传先查幂等，
  再验 preview 到期"的第四象限；既有 replay 测试用未过期 preview、
  expired 测试用全新 key，重排检查次序不会红）。source 域：首次
  confirm 202 → preview 行 expires_at 改过去 → 同 key + 同 digest
  重放 → 202 同 operation id/version、capability 不重发。account 域
  无法测该组合（首次 confirm 即停用，auth 401 在幂等检查之前）。

## 4. 验证证据（随切片填）

- 首提交：全量 pytest（含新测试 ×2）、ruff 同形双命令、pyright、
  OpenAPI 零变更预期（本提交不开 API 面）。
- 切片 1 主体：新增 tests/integration/test_data_api.py 18 例（capabilities
  诚实性 / account 与五种 source 预览计数与 owner 隔离 / 404 所有权 /
  memory 整链 / include_history 422 / confirm 全登记断言（屏障 scope+
  target、清理项 payload ids、抑制 HMAC≠原文、X-Data-Generation=2）/
  幂等重放同 op / 同 key 异 preview 409 / 闭包漂移 409 / 过期+错摘要
  409 / 同 scope 在途 409 / 操作读取 owner 隔离 404 / **IntegrityError
  收敛（双 monkeypatch：前置 SELECT 失明两次 + INSERT 抛唯一冲突 →
  收敛 winner 同 op）** / 账号删除停用+撤销+能力一次吐出+摘要落账 /
  account 清理项含 CLEAR_REDIS 字面量）；迁移往返（scratch 库
  upgrade→downgrade→upgrade 含 a9c41f7d2e83）+ autogenerate 零漂移探针
  0 op；OpenAPI 65 路径（+4）重生 + check_contract_drift --require-zod
  绿（DataSafeError 改名后无组件撞名）；ruff 同形双绿；pyright 0。
  终轮全量（空载重跑）：**391 passed, 8 skipped**——7 skip =
  conftest 深夜窗口守卫（plan/focus 当日排程测试，本地 23 点后自跳，
  与本切片零交集、CI 任意时刻跑当绿），1 skip = S3_ENDPOINT_URL 环境项
  （CI 设该变量）；非未披露红。
- 评审修订：test_data_api.py 全文件 19 passed（新组合测试含）；ruff
  同形双绿；pyright 0；测试独 delta，无 schema/API 变更（OpenAPI/
  drift 不受影响，CI 复核）。

## 5. 实现期判断（待 B 核）

1. **并发败者的 confirm 可能多吃一次代际 bump**：users 行锁串行化后，
   败者锁内幂等复查返回 winner 同 op，但其 bump 已执行——代际多消耗
   一次。方向安全（fail-closed：多失效在途工作），频率 = 并发同 key
   竞态窗口；不入回滚位。
2. **抑制上游锚点**：events 优先 provenance.upstream_id、缺失回落
   event id；file/chat 用行 id。真 connector（P0-6）落地时
   upstream_id 面已占用；切片 3 重采拦截沿用同锚点。
3. **audit 脱敏清理项复用 DELETE_RELATIONAL**：item_ref
   `audit_logs:redact` + payload `{"redact": true}` 判别，不扩枚举
   （零数据期加 REDACT 枚举反而多一个迁移面）；切片 2 executor 按
   payload 分派。
4. **ChatMessage 版本戳用 created_at**（不可变行无 updated_at）；
   digest 的内容版本语义对该族退化为"创建即版本"，对本片删除闭包
   等价（消息不可变，闭包成员变化即 digest 变化）。


- **切片 2 主体（2026-10-06）**：
  - **闭包（裁定①落码）**：event 闭包按 D-028 锚（task.(source,
    source_upstream_id) ∈ 被删事件 (source, provenance.upstream_id)）整删
    派生 task（无边也入闭包——修切片 1 漏删），锚定 task 的
    focus_sessions 显式枚举（FK CASCADE）；仅 task_events 边关联的
    task 去相关存活（边随事件行 CASCADE 消失——修切片 1 过删）；
    tasks=anchored_derivation / task_events=decorrelated 分列
    reason_code，plan_items SET NULL 后果记 limitations。account 闭包
    补 users 行本体；audit redact_ids 从占位符改真实行 id。
  - **清理项**：DELETE_RELATIONAL 统一携带 {"ids"}（account 亦然——
    id 寻址在 FK 图下与顺序无关，audit 行在 users 行 SET NULL 后仍可
    定位）；redact 项 payload {"redact": true, "ids"}；redis 项携带
    {"member": user_id}（SREM 成员，绝不 DEL 共享键）；对象键新增
    storage_objects VERIFY 项（三分）；account 额外登记 owner 全部
    导出包 DELETE_OBJECT 项。
  - **executor**（data_executor.py）：四 phase 检查点持久化；
    fence 清 memory embedding + recompute 行；逐项执行先读 payload
    再分派（redact 判别 + 非 audit redact 拒执行）；退避梯/租约复用
    P0-1 基座（claim 扩 operation/action 过滤 + park_cleanup_item
    立即停车）；RETRY_WAIT 含 next_retry_at；FAILED 结算列剩余项且
    屏障不动；COMPLETED 释放 source/memory 屏障（account 永不自动
    释放）+ 作废 owner 导出 op；行 verify=计数、对象 verify=stat
    三分（仅确证 404 为擦除证据）、audit verify=行在且已脱敏（反向
    断言，列取回 Python 侧判空）。
  - **storage.stat**：exists() 语义保持（既有调用方），新增 stat()
    四值三分（exists/absent/forbidden/unavailable；ClientError code
    404/403/网络分类）。
  - **exports**（data_exports.py）：collect 一事务全族快照（21 直属
    + plan_items/mutations/task_events join + audit 无内容回执视图）；
    ZIP=分族 JSONL+manifest+README（archive-relative）；manifest 含
    schema/graph/snapshot/generation/family_counts/entries(sha256+
    size)/排除类目/include_files/omitted_files；**manifest 不含自身
    checksum（自引用）**；embeddings/credentials/账本/投影排除；
    package→staging（exports/{owner}/{op}.zip）；verify 重读重算
    全部 entries 才 READY（+24h expires_at）；download=owner auth +
    no-store + 仅 READY（EXPIRED=410）；并发删除（generation/屏障/
    用户行三查）在任何 phase 与 download 作废（FAILED
    invalidated_by_deletion）；cron expire READY→EXPIRED+删对象；
    capabilities.export_enabled 翻 true。
  - **recover/receipts/retry**：confirm 记 request_digest（canonical
    JSON SHA-256，双端 fixture 钉住）；receipt 增 10min 加密交付缓存
    （HMAC-SHA256 密钥流：secret 派生 + owner/op/nonce 绑定，计数器
    扩展；单次使用；窗口外清除并统一 404）；POST /deletions/recover
    =原 JWT 身份（停用可走，get_current_identity 不查 is_active）+
    双限流（身份 3/10min + IP 10/10min，429 带 Retry-After——挂错误
    headers 而非 response，防异常响应丢弃）；GET /receipts/{id}=
    Authorization 头能力（不进 URL）+ 统一 404；POST /operations/
    {id}/retry=expected_version 单字段（409 version_conflict 天然幂等），
    仅 source/memory、FAILED/RETRY_WAIT 可重试，重置梯、同 op、
    屏障不动。
  - **worker**：run_data_operation（按 kind 分派；StorageError→
    RETRY_WAIT+30s）；sweep_data_operations cron 30s（QUEUED/到期
    RETRY_WAIT/超时 RUNNING 重派 + 导出过期）——API 侧无 Redis 客户端，
    cron 即唤醒，DB 账本为真（契约 §2.5）。
  - **迁移 b52d7e91ac04**：data_operations.request_digest/
    export_include_files + data_receipts.delivery_{nonce,ciphertext,
    expires_at}；账本形状不变（owner_handle 值键控无 FK）。

- **切片 3 主体（2026-10-06）**：
  - **write_guards 门面**：assert_write_allowed（屏障 + 代际复合检查，
    BarrierConflict/GenerationStale 转译为带 scope 的 WriteBlocked）/
    is_suppressed（upstream_id HMAC 锚查 data_suppressions，released_at
    IS NULL）/ release_source_suppressions（幂等释放 + 无内容 audit）/
    current_generation_of。SuppressedSource 409 code=source_deleted。
  - **事件入口**：create_event 在 dedupe 查找**之前**查抑制（已删事件
    重放拒绝而非静默复用）；batch 对 SuppressedSource 逐 envelope 转
    rejected（队列其余项不受污染）。POST /events/batch 增
    X-Data-Generation 入口检查（缺头=旧客户端兼容窗照常；带旧值=
    409 generation_stale，live 值挂错误 headers——route response 头
    会被异常响应丢弃，判断④第二次实证）；响应恒带 live 值，绝不
    自动补齐缺头客户端。
  - **写路径接线**：chat send（session id 入 SOURCE 屏障）、memory
    create（引用 event ids 入 SOURCE）、memory_lifecycle 四写路径
    （行 id 入 MEMORY + 引用 event ids 入 SOURCE）、focus create/
    update（task id，语义=account 屏障覆盖）、agent_runner（run 入口
    + 两次 provider 写回后复查 → CANCELLED §2.4；action 入口 + 工具
    后 → FAILED + lifecycle code；basis references 按 kind 入对应
    屏障空间）、material_ingestion（run_extraction 入口 skip
    deletion_barrier；embed 写回前复查代际，旧向量不落列）。
  - **投影**：flush_state_recompute 对 account 屏障 skip（死行上不
    fresh derive；§2B-3）。
  - **孤儿账本**：storage_orphan_keys 表（storage_orphans.py 服务）+
    迁移 c7a3f02d9e51；files.py 行删同事务 register、对象删成功内联
    release；worker drain_storage_orphans 改 DB 领取（租约 + 退避梯 +
    FAILED 停车），Redis SADD/SPOP 删除，enqueue.py 该对函数移除；
    registry 条目改指新表；account 清理项不再有 storage:orphans
    Redis 字面量。
  - **account 闭包**：data_suppressions 行随账号终结
    （reason_code=account_termination）；_account_closure 增 handle
    参数（owner_handle 查询一次）；executor 家族表补
    data_suppressions。
  - **memory confirm 修复**：抑制登记收窄到 source 域（memory 域
    confirm 曾 KeyError source_kind——潜伏自切片 1，守卫测试首次
    触达即炸，见 §2B 注记）。

- 切片 2 主体：新增测试 executor 8（四 phase 完成与分区存活/对象失败
  退避 RETRY_WAIT 恢复/verify 403 拒结算且治愈后完成/redact 错路由
  拒执行 + account 脱敏保行/FAILED 停车屏障不释放 + 手动重试同 op
  恢复/version 冲突 409/account 结算含导出作废与 redis 成员移除）+
  exports 8（READY+download no-store+manifest checksum 全复算/
  include_files=false 明确遗漏/幂等含 include_files 409/仅 READY/
  owner 隔离/并发删除作废/24h 过期 410+对象删/audit 无内容视图）+
  recovery 8（fixture 双样本钉 digest/密封往返含绑定失败/停用身份
  一次性恢复/窗口外统一 404/错摘要+未知键+source 域不可区分 404/
  429 Retry-After/能力读回执/无效-缺失-过期能力统一 404）+ API 适配
  （capabilities export_enabled=true、裁定①分区 preview、audit
  redact 真实 id 顺序无关断言、redis member 断言）。**全量终轮：
  423 passed / 1 skipped**（S3_ENDPOINT_URL 环境项，CI 设该变量；中间
  轮曾 1 failed=audit id 无序 SELECT 顺序漂移的测试自身缺陷，改顺序
  无关断言后复跑全绿——非产品面回归，如实记档）；ruff 同形双绿；
  pyright 0；OpenAPI **70 路径（+5：exports/
  download/retry/recover/receipts）** + check_contract_drift 绿；
  迁移往返（scratch 库 upgrade→downgrade b52d7e91ac04→upgrade）+
  autogenerate 零漂移探针 0 op，scratch 已删。

- 切片 3 主体：新增 tests/integration/test_write_guards.py **19 例**
  （抑制四：重采跨 client_event_id 拦截含 batch 逐 envelope rejected /
  重授权解除后可复用 / 无 upstream_id 照过 / 服务层异常型；代际一：
  batch 缺头兼容 + 匹配头通过 + 确认后旧头 409 且错误头带 live 值；
  屏障三：barred session 收消息 409 与无干 session 202 / barred memory
  correct 409 / 新 memory 引 barred event 409 与无引用 201；§2.4 三：
  run 入口 CANCELLED+source_deleted 零 provider 调用 / 模型调用中途
  bump 代际 → CANCELLED 不写结果不写回复 / CONFIRMED action → FAILED
  + last_error.code；extraction/投影三：barred file 抽取 skip 且零
  chunk / embed 中途 bump 代际向量不落列 / account 屏障下投影 skip
  含正向对照；孤儿三：删除失败留 durable 标记且 drain 治愈 /
  成功路径内联释放零残留 / 幂等登记 + 梯尽 FAILED 停车不可再领；
  account 闭包二：抑制行终结 + receipt 存活 / 锚定 task 带暂态编辑
  仍整删（E7-3 钉））。**全量终轮：442 passed / 1 skipped**（S3 环境
  项；ruff 同形双绿、pyright 0、OpenAPI 70 路径 + drift 绿）。迁移
  c7a3f02d9e51 往返 + 零漂移探针见终轮记录。修复三处既有面：memory
  confirm 抑制 KeyError（潜伏 bug）、account 清理项测试的孤儿
  Redis 字面量断言、registry 新表登记（inventory 在开发期抓到
  一次——fail-closed 自证第二次）。
- 评审修订（2026-10-06，B RC 唯一必改项 = 核点 3）：抑制先于
  dedupe 的次序钉死。原 helper 每次随机 `dedupe_key`，重放载荷永不
  命中 dedupe 查找——重排 create_event 次序不会红。新增
  test_suppression_precedes_dedupe_in_barrier_window：seed 与
  replay 均不带显式 dedupe_key（同 source+provenance → 后端计算键
  相同），三段式夹住——屏障前同载荷重放先实证 200 +
  `X-Deduplicated: true` + 同 event id（"计算键必命中"前提在测），
  confirm 后同载荷断言 409 source_deleted（此时 dedupe 必命中，
  409 只能来自先行的抑制检查）。变异验证：临时把抑制检查挪到
  dedupe 之后该测试转红，还原复绿。helper 加 explicit_dedupe 开关
  （默认 True，既有行为不变）。文件 20 例；全量 444 passed /
  0 skipped——本地与 CI 实测同值（CI 亦设 S3 变量，S3 项两侧实跑；
  既往记录的 "1 skipped" 为本地未设 S3 的环境项，非 CI 形态）；
  ruff 同形双绿、pyright 0。测试独 delta，生产码零变更。

## 5 实现期判断（待 B 核）

1. **并发败者多耗代际**（切片 1 判断①延续）：无变化，B 已签认。
2. **抑制上游锚**：无变化（upstream_id 优先），切片 3 携带
   "connector 事件必带 upstream_id"前置纪律。
3. **交付缓存加密选 HMAC 密钥流而非新依赖**：cryptography/
   itsdangerous 不在依赖面；构造=HMAC-SHA256(secret, 域分隔 ||
   receipt_owner || op_id || nonce || counter) 计数器扩展 XOR，
   43 字节 token 单块、nonce 一次性、绑定 receipt 属主与操作；
   等价于 HKDF-expand 式单用流。备选是新增 cryptography 依赖走
   Fernet——为一个 10min 单次缓存引入新依赖不值。B 若判应换标准
   库件，属机械替换。
4. **Retry-After 挂在错误 headers 上**：异常路径会丢弃写入路由
   response 对象的头，AppError.headers 是既有通道（WWW-Authenticate
   同款）——429 响应才可靠携带。
5. **recover 限流用进程内 RateLimiter**：契约 §4 要求双限流（身份+
   IP），§6 的 Redis 共享限流是 2API+2worker（E7-9）门；现部署单
   uvicorn worker（rate_limit.py docstring 自认），hit/retry_after
   即替换缝。E7-9 前不提前实施。
6. **account 清理项统一带 ids 而非 owner sweep**：id 寻址在 FK 图
   下与执行顺序无关（users 行 CASCADE 何时发生不影响其余项），
   audit redact 本就必须 id 寻址（user_id SET NULL 后无法按属主
   定位）——统一形状消掉 sweep 分支。
7. **行 verify 用计数、audit verify 用列取回 Python 判空**：同栈
   上 count()+OR(列 IS NOT NULL) 与同事务列读曾给出矛盾结果
   （开发期实证一次），列取回形态经对码验证读的是 UPDATE 后真相；
   语义等价、形状保守。
8. **exports 不升代际不设屏障**：导出不删除不改事实层；并发删除
   以 generation 快照 + ACTIVE 屏障 + 用户行三重检查作废（任何
   phase 与 download 时点），READY 后过期由 cron 翻 EXPIRED 并删
   对象。
9. **manifest 不含自身 checksum**：自引用无解；verify 复算 manifest
   所列全部其它成员。README 计入 entries。
10. **抑制拦截只匹配 upstream_id、不做行 id 回落**：登记侧锚
    （upstream_id 优先，event id 回落）在删除后对新事件不可达——新
    envelope 无从知晓已删行的 id，回落在拦截侧是死代码；无
    upstream_id 事件照过（manual/test 源），connector 强制前置纪律
    随 P0-6 落（任务书 §3 记档，B 携带①已收）。
11. **解除路径不做 HTTP 面**：A 稿 §4 冻结矩阵无 release 路由；服务
    层 release_source_suppressions 幂等可测，触发面等 P0-6 connector
    重授权流（谁触发"重新授权"是产品面裁定，非本片）。
12. **投影对 source/memory 豁免**：投影非 id 分区，source 屏障下
    无干 task 仍应投影；闭包后 fence 的 recompute_ids 收敛它。仅
    account 屏障 skip（整个 owner 在死，fresh derive 全是死行白工）。
13. **§2.4 用 CANCELLED（run）/FAILED（action）而非新终态**：两枚举
    均已有值、CHECK 不动；lifecycle code 放 failure/last_error.code
    （account_deleted/source_deleted），客户端可从 code 区分而不需
    新状态机。
14. **storage_orphan_keys 无 owner 列**：key 内嵌 uuid 可经
    file_objects 反查（registry owner 描述如此声明）；生命周期操作
    的对象清理仍走 data_cleanup_items（自带 owner_handle），本表只
    服务 D-033 旧删除路径——两队列不合并，形状各自最小。
15. **孤儿 drain 用独立 session 而非 operation 上下文**：drain 与
    data sweep 同 cron 进程但互不依赖；claim/execute/release 同事务
    一次提交（storage.delete 成功后 release），崩溃回 PENDING 走
    退避梯——账本为真、cron 即唤醒（§2.5 同构）。
