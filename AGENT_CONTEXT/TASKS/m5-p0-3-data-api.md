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

## 3. 实现记录

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

