# M5 P0-4：数据控制客户端接线（B）

Status: 开工 2026-10-06；基线 main `31e4743`（#74 合并头，P0-3 全链落）。
依据：D-036 §8 实施令；B 稿 `m5-data-controls-grants-client-contract.md`
（冻结 r2）§1-§4；协调人 P0-4 GO 派工（2026-10-06）。

## 0. 边界

- **负责**：/v1/data 客户端契约镜像（D-035 本侧批次：请求面全量 +
  响应面，packages/contracts + fixtures 冻结 + drift 注册表）、
  client 数据 API 模块、Stronghold 回执分槽（按 owner 命名，含 recover
  留存元数据）、X-Data-Generation 同步接线（捕获/回发/409 再基）、
  无主 Focus 草稿 adopt/discard、数据控制页（导出/删除/回执/本机清理
  状态面）、回执独立最小视图（登录屏入口，capability Bearer 直连）。
- **不负责**：GrantScopeCatalog 与 grant 面板值级面（A 侧端点未落，
  B 稿 §5 为待裁增量——端点冻结后另行切片）、E7 执行、许可盘点主体
  （P0-6 可提前启动，独立交付）、服务端语义。
- **切片**：
  - **切片 1（本 PR）**：契约镜像 + drift 注册 + client 数据 API +
    Stronghold 回执分槽 + 无主草稿处置原语 + X-Data-Generation 接线。
    无 UI。
  - **切片 2**：数据控制页 + 回执最小视图 + 本机清理状态机 + 无主
    处置 UI。

## 1. 冻结形状对照（B 稿 §1/§3/§4）

- **镜像纪律**（M4 三教训代码化）：全部显式 `z.object`；A 稿 `?` 记号 =
  字段必有但允许 null → `.nullable()` 必填键，禁止 `.optional()` 顺手。
  本批 nullable 位（对照 OpenAPI 实测）：DataOperationOut.
  next_retry_at/expires_at/error/receipt_id/receipt_capability、
  OperationProgress.total、DataReceiptOut.completed_at/backup_expires_at。
  receipt_capability 仅创建/恢复交付、普通读取恒 null。
- **DataSafeError 组件名备忘**（#72 互审）：OpenAPI 组件名
  `DataSafeError` = 冻结文本 SafeError DTO（避让 agent 域既有
  `{code,message}` 组件）；Zod 注册按组件名 DataSafeError。
- **retry 输入 = expected_version 单字段**（@A-r2 字段 delta）：409
  version_conflict 即天然幂等，与 M4 confirm 同构。
- **recover 三件套留存**：删除确认时把完整 POST /deletions 请求体
  （preview_id/preview_digest/client_request_id，全非敏感）+ receipt
  capability 存入按 owner 命名的回执槽位元数据；10 分钟 recover 以
  同体重发参与摘要匹配。
- **回执能力卫生**：不进 URL、日志、剪贴板自动复制、遥测；Stronghold
  槽位 90 天到期；Web fallback 仅内存（B 稿 §3，导出脱敏文件随切片 2）。
- **X-Data-Generation**：批推响应捕获 → 按 owner 持久
  （`agenthu.data-generation:{owner}`）→ 下批回发；409 generation_stale
  → 停发重试梯、上报再基（重取状态；被抑事件由服务端 rejected 原因
  自然出队，客户端不做权限判定）。
- **无主草稿**：P0-2 遗留 advisory（处置面归 P0-4）——本片落
  adopt/discard 原语（Rust + TS），目标 cursor 优先语义与事件队列一致。

## 2. 强制携带

1. **audit retryable 语义注记**（#73 B 注记，协调人令"顺手处置"）：
   "audit receipt rows missing" retryable=True 重试不救回缺失行、保守
   走梯后 FAILED 落账——记入本任务书转 E7-3 账面（A 的 E7 fixtures
   期并档），无代码动作。
2. **旧 DELETE 入口原语义**（B 稿 §1）：切片 2 UI 不得把旧 204 渲染为
   全量擦除；「永久删除/全账号删除」仅经 /v1/data。
3. **恒有可空 vs 可省**：镜像落地后 fixtures 冻结快照同步 +
   `check_contract_drift --require-zod` 绿为硬门。

## 3. 实现记录（随切片填）

- 切片 1（2026-10-06）：
  - **契约镜像**（packages/contracts +17 schema）：DTO 按 OpenAPI 组件
    逐字段镜像；恒有可空位（next_retry_at/expires_at/error/receipt_id/
    receipt_capability/total/completed_at/backup_expires_at）一律
    `.nullable()` 必填键；include_files 为唯一可省略请求字段；枚举以
    const 数组单一来源内联（drift 解析器读 z.enum 字面量不读 schema
    引用——首轮真红抓到，见 §5-1）；fixtures 冻结快照同步；
    check_contract_drift 注册 14 项映射（7 请求向 + 7 响应向）。
  - **client 数据 API**：BackendClient +8 方法（capabilities/previews/
    deletions/exports/operations GET/retry/recover/download）+
    pushEventsTracked（X-Data-Generation 双向）；BackendHttpError 增
    信封 code（generation_stale 可辨）。
  - **data.ts**：canonicalJson/deletionRequestDigest（冻结 fixture 双
    样本逐字复现，自包含 SHA-256）+ fetchReceiptWithCapability
    （capability Bearer 直连，失败一律 null 无枚举面）。
  - **Stronghold 回执分槽**（vault.rs read/write/clear_receipt + lib.rs
    receipt_get/set/clear 命令）：每 owner 独立快照文件 receipt-{owner}.
    .hold + 独立 keyring 凭据；owner 字符校验（8-64 ASCII 字母数字，
    防路径注入）+ 8KB 上限；TS ReceiptStore（Stronghold 实现 + Web
    内存 fallback，损坏载荷删除式读取）。
  - **无主草稿处置**：Rust focus_adopt_unowned/focus_discard_unowned
    （目标优先，unowned 自身拒绝）+ TS 两实现同语义（返回实际迁移数）。
  - **代际接线**：generation.ts（owner 命名空间 localStorage）+
    coordinator dataGeneration 选项（捕获回写/兼容窗不补值/
    generation_stale → GenerationStaleError 即时中止清空存储）+
    services.tsx 注入 + AppServices.receipts。
- 切片 1 RC 修复（2026-10-06，A 互审 @f444951 唯一必改 + 三注记）：
  - **解析器兑现枚举/nullability 钉**：_collect_consts 多行 const 数组
    （bracket-balance）；z.enum 参数展开 consts（不可解析裸引用构造性
    报错——空枚举盲区变硬失败）；对齐段增枚举全集比较 + response 向
    nullability 不对称检查；变异单测双钉（改枚举值红/去 .nullable() 红）。
  - **/v1/data 三真实响应样本**（capabilities GET + preview POST +
    confirm→operation GET，集成无 worker 形态）；receipt 样本缓释
    （原因见 §5-8）。
  - **completion_scope 收紧** z.string() → const 数组枚举；**存量镜像
    缺口 7 处修复**（§5-7）+ UI 两处可空守卫；fixtures 头部恢复角色与
    禁手编纪律注记（CI 唯一契约源）。

## 4. 验证证据（随切片填）

- 切片 1（本机；CI 数字以推送头实测日志为准，跑后回填）：
  desktop vitest **220/220**（28 文件；新增 data/generation/
  receiptStore/adopt 处置 + coordinator 代际两例）；tsc 零错；
  cargo test **23/23**（新增 receipt 槽隔离/owner 校验 + 草稿 adopt
  目标优先两例）；ruff check + format --check 同形双绿；
  check_contract_drift --require-zod 无漂移（14 新映射全过）。
  环境注记：worktree node_modules 因早前 /tmp 工作树复制事故损坏，
  全清 pnpm install 重建（与代码无关，如实记）。
- 切片 1 CI 实测回填（推送头 9768a7d，Actions 日志取数）：
  desktop **220/220**（28 文件）+ contracts 17/17；tauri-rust cargo
  **23/23**；Backend/Compose/Docker/audit 全绿；同机数一致。
- 切片 1 RC 修复（本机 @0d4050f）：drift 单测 **21/21**（+5：const 展开
  两例/fixture 枚举探针/双变异钉）；全 unit 121 passed；drift
  --require-zod 双源无漂移（7 处存量缺口修复后）；ruff 同形双绿；
  contracts 17/17 + tsc 零错；desktop vitest **220/220** + tsc 零错
  （plans 测试 fmt 助手可空化）。
- 切片 1 RC 修复 CI 实测回填（推送头 0d4050f，双跑取数）：
  Backend 双跑均 **444 passed + 7 skipped**（skip 全为晚间断言守卫
  conftest.py:65——CI 时点北京 22:5x 撞 <130/65 分钟窗，非本片测试；
  算术：437 存量 + 7 新增 = 444）；drift 步双跑 "No contract drift
  detected"；frontend/tauri-rust/Compose/Docker/audit 12/12 全绿。

## 5. 实现期判断（待 A 核）

1. **枚举内联而非 schema 引用**：drift 解析器 _SCHEMA_RE 只收录
   z.object 导出、字段引用按 \w+Schema 解析为嵌套 object——首轮
   真红（"OpenAPI declares ['string'] but client expects ['object']"+
   引用 not found）证明引用式枚举镜像与检查器不兼容。采用 const
   数组单一来源（值与 TS 类型不可分叉）+ DTO 内联；不注册独立枚举
   映射（作为嵌套字段已覆盖）。
2. **generation_stale 不进重试梯**：同代际重发必然再 409；即时中止
   + 清空存储进兼容窗（下次无头推 = 重对齐，被抑条目由服务端
   rejected 原因出队）。事件保留原 owner 队列。
3. **回执 owner 字符校验双层**（Rust receipt_slot_path + vault
   receipt_owner_valid）：owner 进文件名与凭据名，路径注入是本片
   唯一新攻击面；TS 侧不重复校验（单一防线在边界）。
4. **TS adopt 返回值对齐 Rust**（实际迁移数而非存在数）：首轮测试
   抓到两侧语义分叉后修齐——目标已有草稿时清除无主行返回 0。
5. **解析器四盲区收口（RC，A 双变异实证）**：const 数组方案原未兑现
   "作为嵌套字段已覆盖"——`_CONST_RE` 单行正则不捕多行 const 数组、
   `z.enum(CONST)` 参数不展开 consts，三组枚举解析为空集（探针
   `enum=()`）；双副本同改枚举值/去 `.nullable()` 双变异均仍绿（后端
   加枚举值→快照重生→镜像未跟→CI 绿→用户面前 parse 红的后果链）。
   修复后变异即红；残留已知面：`z.literal` 字段（targets kind /
   confirmed / include_history）不进枚举比较——zod 运行时 + 真实载荷
   样本兜底。字段级人工交叉评审仍是主防线（D-035 注记第四例再证）。
6. **completion_scope 收紧为枚举**（注记①处置）：后端
   `Literal["controlled_live"]`，镜像 z.string() → const 数组枚举——新
   scope 值 parse 红而非静默渲染，与 kind/status/phase 同哲学；不采
   松动记由路线。
7. **强化检查器首跑即抓 7 处存量镜像缺口并修复**：ClientCurrentState
   .updated_at 与 ClientPlanItem.task_id/start_at/end_at（后端 `X | None`
   序列化显式 null，M4 期 null 加宽盲区残留）镜像补 `.nullable()`；
   PlanView/ReplanSuggestion 两处 `new Date(start_at)` 补可空守卫
   （无窗 plan item 为真实可达形状）。
8. **receipt 样本缓释**：receipt 行由 worker 完成态产生，集成环境无
   worker 面；receipt 形状由 E7 栈端到端钉（E7-2/E7-5 预登记面）。
   capabilities/preview/confirm→operation 三样本覆盖 kind/status/phase
   与全部恒 null 键。
9. **TS unowned adopt 静默返 0 vs Rust 报错**（注记③处置）：可接受
   不对称——Stronghold 命令层对 unowned 目标显式报错，Web fallback
   （无命令层）返 0 无副作用；单一显式防线在命令层。
