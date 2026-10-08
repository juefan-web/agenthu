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
  - **切片 1（已合并 #75）**：契约镜像 + drift 注册 + client 数据 API +
    Stronghold 回执分槽 + 无主草稿处置原语 + X-Data-Generation 接线。
    无 UI。
  - **切片 2（本 PR，基线 main `8efd84b`）**：数据控制页
    （capabilities 卡 + 导出全流 + 删除全流含账号两步确认 + 状态文案表
    + poll 5s→30s/30min/visibilitychange）+ 回执独立最小视图（登录屏
    入口，receipt_list 槽位枚举去 capability，不经业务会话/RQ）+ 本机
    清理状态机（not_started→cleaning→verified/failed，verified = 可复
    跑检查输出：键存在性/SQLite 行数/token 槽清空；账号路径 VACUUM，
    回执槽不动）+ 无主处置 UI（队列计数 + 草稿在场，adopt 需在席会话
    ——#69 advisory #4 live-session ownerKey 守卫；discard 恒可用）。
    Rust 增量：queue_clear_owner/queue_count_owner/receipt_list 三命令。
    **红线**：额度不自算（P0-5 裁定④——本片无额度面）；venue 不接入
    （P0-6 红线）；旧删除入口语义不动。

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
- 切片 2（2026-10-07，基线 main `8efd84b`）：
  - **Rust**：queue_clear_owner（行级清除 + WAL checkpoint + 账号路径
    VACUUM）/ queue_count_owner / receipt_list（目录扫描槽位，构造性
    剥离 capability，损坏槽跳过）；测试 +2（owner 范围隔离 / capability
    不出列表）。
  - **队列/存储面**：OwnerCleanupApi（clearOwnerData/countOwnerData，
    owner 显式入参——清理运行在登出后）；Local 实现含损坏隔离备份键
    清除；ReceiptStore.list()（槽位枚举非敏感元数据）。
  - **数据控制页**（features/data-controls/）：statusCopy（B 稿 §2 冻结
    文案表逐条落地：preview 行/QUEUED-RUNNING/RETRY_WAIT/FAILED/
    COMPLETED/READY/EXPIRED/未知状态停危险操作/409 与已知码）；导出
    面板（include_files 默认勾选、client_request_id 稳定幂等、READY 才
    下载、"不含未同步草稿"明示）；删除全流（source/memory 单确认、
    account 两步 + checkbox「我理解此操作不可恢复」+ 可读身份 +
    不自动代导出）；poll 钩子（5s→30s 梯、30min 上限、visibilitychange
    暂停/回前台新鲜拉取、手动刷新只 GET）；无主处置卡（adopt 需在席
    会话——live ownerKey 守卫，discard 恒可用）；本机清理卡（状态机
    展示 + 可复跑检查清单 + failed 重试/verified 重新核账）。
  - **回执独立最小视图**（ReceiptViewer）：登录屏入口（未登录/401 态
    可见）、不经业务会话/RQ、capability 仅内存中转（槽位→直连请求）、
    无效能力统一「回执不可用」、手动刷新。
  - **本机清理状态机**（cleanup.ts）：not_started→cleaning→verified/
    failed；顺序 = logout（业务 token 槽，回执槽不动）→ 队列清除 →
    草稿清除 → 代际清除 → 检查（键存在性/行数/代际/token 面，回执槽
    为恒 ok 信息行）；verified = 全部检查通过。
  - **AppServices** 增 resolveOwner；App 增「数据与隐私」视图与登录屏
    回执入口。
  - **CI flake 修复**（切片 2 首推后追加）：vault `key()` 对 Windows
    Credential Manager 的读写无重试、错误被 `|_| VAULT_ERROR` 泛化吞掉
    （CI 红时无从定位底层原因）。修复 = 有界重试（3 次/150ms 间隔，
    仅瞬时类 NoStorageAccess/PlatformFailure；NoEntry 等确定性结果
    直通）+ 底层错误保留进消息（至多携带凭据 target 名，与本地回执
    文件名同敏感级，不含密钥本体）+ 密钥只生成一次（重试写同一密钥）
    + 重试机制单测两例（耗尽/直通/恢复）。
  - **活雷①补落**（预核指出后追加）：`backend_proxy.rs` 请求侧与
    响应侧白名单各加 `x-data-generation`（D-036 §8-3 代际双向线：
    批推请求带客户端持久代际、确认/批推响应带 live 代际）；照
    x-next-cursor 先例新增响应侧单测（透传 + Set-Cookie 仍拦 +
    无关自定义头仍剥），forward 单测扩代际头断言。此前桌面端双向线
    全断——客户端拿不到 live 代际 ⇒ 停在旧代际 ⇒ 409
    generation_stale 防护恒不触发，E7 客户端面必踩。

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
- 切片 2（本机 @504e823；CI 数字以推送头实测日志为准，跑后回填）：
  desktop vitest **244/244**（+24 新例：statusCopy 7 / poll 3 / cleanup
  6 / DataControlsView 5 / ReceiptViewer 3；另 4 个存量视图测试文件补
  resolveOwner 注入）；desktop + contracts tsc 零错；cargo test
  **25/25**（+2：owner 范围隔离清除 / receipt_list 剥离 capability 与
  损坏槽跳过）；clippy 无新告警（material_transfer 两处存量告警非
  本片，CI 不门控）。
- 切片 2 首推 CI 红 + flake 修复（本机，修复头见 git log）：首推
  504e823 双跑中 push 事件跑（run 37629858921）tauri-rust FAILED——
  `vault::tests::receipt_slots_isolate_owners_and_reject_bad_keys`
  panicked vault.rs:159:53 `Secure session storage is unavailable`
  （24 passed/1 failed）；同 SHA pull_request 跑（37629870462）全绿；
  两跑同镜像 windows-2025-vs2026。定位：失败点 = 写成功后紧接的读
  →CredRead 瞬时故障（keyring get_secret），且泛化错误吞掉底层原因。
  修复后本机 cargo **27/27**（+2 重试机制单测）；CI 回填待新头双跑。
- 切片 2 CI 实测回填（修复头 49658cf，双跑全绿 12/12，Actions 日志
  取数）：tauri-rust cargo **27/27** 双跑一致（push 5.03s / PR 5.02s，
  含 keyring 重试两新例）；frontend contracts **17/17**（1 文件）+
  desktop **244/244**（33 文件），与本地同数；Backend 双跑
  **447 passed + 6 skipped**、drift 步双跑 "No contract drift
  detected"、ruff All checks passed（本 PR 零后端改动，447/6 为 main
  现状数，skip 归因非本片面）；Compose/Docker/audit 双跑全绿。
- 活雷①补落（本机）：cargo **28/28**（+1：data-generation 响应侧
  透传；forward 测试扩断言）；backend_proxy/vault clippy 零告警
  （material_transfer 存量 3 条非本片）。
- 活雷①补落 CI 实测回填（头 b97e972，双跑全绿 12/12）：tauri-rust
  cargo **28/28** 双跑一致（pull_request 5.02s / push 5.04s）。

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
10. **回执视图手动刷新**（切片 2）：B 稿只冻结了 operation poll 参数
    （5s→30s/30min/前后台），回执视图的轮询节奏未冻结——本片只做
    手动刷新（GET），不擅自定参；账号删除后的状态面 = 回执视图 +
    本机清理卡（owner 401，不 poll，B 稿 §2 收紧原文）。
11. **token 单槽非 owner 维度**：backend_token_* 是单槽（无 owner
    列），清理检查的 tokenPresent 探针按环境注入（Tauri =
    backend_token_get；Web = null）；null 时检查行如实标注「当前环境
    无持久凭据面，未检查」，不伪 verified。
12. **损坏隔离备份随 owner 清除**：queueCorruptKey 保留原 payload
    （用户内容面），clearOwnerData 一并移除；SQLite 面的行级清除在
    Rust 命令内（无隔离表）。
13. **被删来源的本地待同步事件不预清**：服务端抑制 + rejected 出队
    （切片 1 coordinator 机制）自然处理；「客户端不是权限判定者」
    （B 稿 §4）——COMPLETED 文案明示该行为。
14. **campus 会话不动**：独立于 Backend 账号；B 稿「共用会话先隔离或
    停自动复用」是后续边界，本片以说明文案 + 顶栏退出按钮承接。
15. **测试形态**：fake timers 下单发 advanceTimersByTimeAsync(全量)
    不驱动 .then 链里排程的定时器——cap 用例改 30s 步进推进（≤70 步
    必跨 30 分钟）；waitFor 在假钟下会饿死，改 advance(0) 微任务冲刷。
16. **keyring flake 修在根因而非重跑**（切片 2 首推 CI 红处置）：
    同 SHA 双跑一绿一红 + 失败点在「写成功后紧接的读」= CredRead
    瞬时故障，坐实环境抖动而非代码回归。选择有界重试 + 错误保留
    （AGENTS.md §7-2 外部调用重试上限 + 可观测），而非 `gh run rerun`
    碰运气——每次推送双跑两票，重跑不改中奖率。NoEntry 直通不重试
    （确定性结果重试会把「确实没有」拖成延迟失败）；错误长度（≠32B）
    同为确定性损坏态，不重试。密钥生成一次、重试写同一密钥——避免
    半写状态。附带发现（不本片处置）：main 上 material_transfer.rs
    存在 fmt 漂移与两条 clippy 告警（unused import/TRANSFER_TIMEOUT
    dead code/useless format），CI client.yml 不跑 fmt/clippy 故不
    门控；`cargo fmt` 全 crate 会重排 5 个无关文件，本片手工回退保持
    diff 仅 vault.rs。
17. **新增自定义响应头 ⇒ 同步查代理两侧白名单**（活雷①教训）：
    D-036 §8-3 设计了 X-Data-Generation 双向线，后端（events/data
    端点）与 TS 客户端（client.ts 发送+读取、generation.ts 持久化）
    均已各自落地，但 Rust `backend_proxy` 的请求/响应白名单未跟——
    桌面端所有 backend 流量经此代理，白名单是隐形的第三端，缺一侧
    即断线且无任何报错（头被静默剥掉）。教训：契约新增自定义请求/
    响应头时，桌面侧要查的不是一个点而是三个点（TS 调用面、代理
    请求白名单、代理响应白名单）。流程面教训：协调人「随切片 2 修」
    的处置当时未落进本任务书 §0 边界，实现时即被挤出——外审处置
    必须先进冻结边界再动手，否则等于没派。
