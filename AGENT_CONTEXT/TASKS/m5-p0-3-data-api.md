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

## 4. 验证证据（随切片填）

- 首提交：全量 pytest（含新测试 ×2）、ruff 同形双命令、pyright、
  OpenAPI 零变更预期（本提交不开 API 面）。

## 5. 实现期判断（待 B 核）

- （随切片记录）
