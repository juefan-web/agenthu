# M5 B 草稿：数据控制、授权面板与本地生命周期

Status: **r2，B 署名修订（2026-10-05）**。r1 是外部 codex 输入材料（协调人
裁定一），不构成共识基线；r2 起 B 认领作者身份——改错、删不认同项、补己见，
修订账见 §8（供 A 互审逐条对照）。基线 bf02eeb；任务边界见
[phase-0](m5-phase0-prereq-docs.md)。Backend 事实层不变；本机清理是客户端
责任，不代表远程设备已清理。本稿所有"提案"均待 phase-0 裁定，不假定现 API
已具备。

## 1. API 与页面责任

复用 backend client/transport、packages/contracts、现 Basis 组件、错误
envelope、Stronghold 与队列适配层，不在 React 执行删除业务规则。页面落
`features/data-controls/`（经 AppServices 注入，离线测试同 M4 视图族模式）：
「数据与隐私」聚合现有资料/Memory/Chat 删除入口，「自动执行授权」挂 grant，
「模型数据使用」保留独立 consent。

**逐字段镜像 A 稿 §4** 的 DataCapabilities、DeleteTarget、DataPreview、
DataEffect、DataOperation、OperationPhase、OperationProgress、SafeError、
DataReceipt；manifest 消费 schema_version/graph_version/snapshot_at/
generation/family_counts/entries/excluded_categories。镜像纪律（M4 三教训
代码化）：① 全部显式 `z.object`（drift 解析器不识别 `.extend`）；② A 稿
`?` 记号 = 字段**必有但允许 null** → Zod `.nullable()` 必填键，禁止顺手
`.optional()`（null 显式发射会打爆 optional-only 镜像）；③ 服务端恒发新
字段必须同批进 Zod——单向 drift 检查（客户端 ⊆ OpenAPI）对「恒发被 strip」
零告警，故 contracts 镜像与 OpenAPI 同批其后落（M4 sequencing rule 延用），
tests/fixtures/client_contract.ts 冻结镜像同步，`check_contract_drift.py`
注册表登记新映射；字段级人工 cross-review 仍是主防线。

operation.version 必有；receipt_capability 仅创建/恢复交付、普通读取为
null。**路由输入同步镜像**（@A-r2 `581606a` §4/互审 §6 字段 delta）：
`POST /operations/{id}/retry` 输入 = `expected_version` 单字段——409
version_conflict 即天然幂等，不引入第二个幂等键；客户端双击重试的第二发
落 409 → 重取 operation，与 M4 confirm 的 expected_version 模式同构。
无 capabilities 时显示「此服务尚未支持完整导出/删除」；
minimum_client_version 只控制新面显隐，不阻塞既有功能；**旧客户端不识
/v1/data 时，旧 DELETE 入口保持原语义可见**（防「无处可删」）。旧 DELETE 的 204
不得渲染为全量擦除——旧入口保持原语义（隐藏/归档/单条删除）与如实文案，
「永久删除/全账号删除」仅经 /v1/data。业务 401 退出后 receipt 读取走
**独立最小视图**：从登录屏入口进入，不依赖 AppServices 业务会话、不进
React Query 业务缓存，用 capability 作 Bearer 直连。receipt 能力从不进
URL、日志、剪贴板自动复制或遥测。

## 2. 导出与删除流程/文案

导出：含文件默认勾选 → 提交一个 client_request_id → 操作进度 → READY 才
下载 → 到期禁下载。幂等键 = (user, kind, client_request_id)：任务重查
返回同一 operation，丢 202 重传同 ID，不每次点击生成新 ID。preview_digest
是不透明回显：原样提交、不渲染、不本地重算。服务端包含敏感全文，下载前
说明本地副本由本人保管、清客户端缓存不擦除任意目录的导出文件。

删除：选择账号/来源/记忆 → preview → 服务端 effects 与 limitations →
独立确认 → 202「删除处理中」→ 查询 receipt/operation → 确认受控在线
清理完成后，再显示本机清理与其他残留。不能离线确认后偷偷恢复联网执行
不可逆删除；离线只保存非敏感选择。账号删除两步确认 + 明确 checkbox
「我理解此操作不可恢复」（不做 type-to-confirm 重交互），先展示可读账号
身份与 preview 计数；用户可以先导出，不默认代他导出。**恢复路径的输入
三件套**（原 JWT 身份、原 client_request_id、同请求摘要）要求客户端在
删除确认时把 client_request_id 留存在 receipt 槽位元数据（非敏感 UUID），
否则 10 分钟 recover 无从发起。

| 状态/情况 | 用户可见行为 |
| --- | --- |
| preview | 「将删除 X 项、清除 Y 项派生内容、重算 Z 项；独立编辑内容按清单保留」。不自推断级联 |
| preview_stale/到期 | 「数据已变化，请重新查看删除范围」；旧确认按钮失效 |
| QUEUED/RUNNING | 「删除已提交，正在清理」；只用服务端 phase/processed/outstanding，无虚构百分比 |
| RETRY_WAIT | 「部分清理尚未完成，系统将在 … 重试」；显示剩余数与安全错误 |
| FAILED | 「删除未完成」；提供同 operation 重试，并列 operation id 与 request-id（联系排查用后者） |
| COMPLETED | 「服务端在线数据已清除」；另列备份最晚失效、供应商说明、本机/其他设备待清理 |
| export READY/EXPIRED | 「可下载至 …」/「导出包已到期」；下载 403/超时不误称不存在 |
| 409 deletion_in_progress | 「已有删除正在进行」；不并发展示第二个删除确认 |
| source_deleted | 复用 Basis 失效展示；不保留 quote/标题/摘要，不再跳转已删来源 |

确认按钮锁定同一 client_request_id；409 重取 preview/version，不后台自动
扩大范围；429 显示 Retry-After；未知状态停危险操作并显示升级提示。
**poll 与手动重试的作用域**（对齐 A-r2 §2 收紧）：operation 轮询与手动
重试仅适用 source/memory（owner 仍可业务认证）；账号删除确认后 owner
认证失效（401），状态查询走 receipt 视图轮询，FAILED 只显示「系统将
自动重试，必要时由运维处置」，不提供手动重试入口。**recover 重发物料**：
客户端在删除确认时把完整 POST /deletions 请求体（preview_id、
preview_digest、client_request_id——全非敏感）留存在 receipt 槽位元数据，
10 分钟 recover 以同体重发参与摘要匹配。
**poll 参数提案**：5s 起步、退避至 30s、前台上限 30 分钟、后台暂停
（visibilitychange）+ 重挂载即新鲜拉取；手动查询只 GET，不重发
DELETE/POST。receipt 恢复失败也告知「清理仍在继续，回执凭据未能取回」，
不能重新开启账号；receipt 视图对无效能力统一显示「回执不可用」，
不区分不存在/过期/身份不符（客户端侧同样不给枚举面）。

永久忘记 Memory 明确「含历史版本」；拒绝（REJECTED）是阻止再派生的不同
动作，不得误称已永久擦除。Chat 隐藏/归档与永久删除分清，说明隐藏内容
拟保留期；冻结改变旧删除按钮语义时同步文案与兼容策略。资料删除 preview
明确回答/引用/派生 Memory 影响；撤销模型同意只停未来发送，不伪称从供应
商立即收回既有内容。

## 3. 回执与本机清理状态机

账号删除确认成功后按序执行：AbortController 停在途请求与 poll → 停
EventSyncCoordinator 循环与 campus poller → 清业务 token 槽（**不动
receipt 槽**）→ queryClient.clear()（receipt 视图状态不在业务缓存内）→
本机清理矩阵。receipt capability 存独立 Stronghold 槽位、按 owner 命名、
90 天到期；Web fallback 仅内存 + 显式导出脱敏回执文件（用户选目录），
不写 localStorage。回执与业务 token 分槽，退出登录只清后者。

本机清理状态机：`not_started → cleaning`（删除确认成功立即进入）→
`verified / failed`；failed 允许显式重试本机清理，期间保持冻结旧队列，
不能返回采集/同步。**verified 判据 = 可复跑的检查命令输出**（键存在性、
SQLite 行数/WAL、槽位清点），不是一次性手工确认——E7 双轮同规格重放。
其他设备是 `unknown/pending`，没有设备响应时不得猜
verified——服务端 COMPLETED ≠ 本机 verified。显示 backup_expires_at 与
provider_limitations，不声称供应商零保留；用户导出的外部副本与无法在线
控制的旧设备均明确说明。

## 4. 本地存储、账号隔离与防复活

实测现状（r2 修正，见修订账③）：**三层存储全部无 owner 维度**——TS 层
localStorage（`agenthu.event-queue` / `agenthu.event-queue.corrupt` 损坏
备份**保存原 payload** / `agenthu.focus-draft`）、Rust 层 `offline.sqlite3`
（QueueDb，backend_proxy 离线队列，**请求 payload 属用户内容面**）、
Stronghold 具名槽（业务 token / campus session）。M5 必须先修此边界，
不能只 queryClient.clear()。

owner_key = canonical backend origin + server user_id（哈希后作存储键与
槽名）；data_generation 独立保存并用于同步。相同校园账号 ≠ 同 Backend
账号。登录/切账号时取消旧请求与 sync 循环；后台闭包不得拿新 token 提交
旧队列（与 EventSyncCoordinator 相容性：队列视图 owner-scoped，协调器
只读本 owner 的 pending 集合）。

| 储存/副本 | 清理与迁移 |
| --- | --- |
| TS 队列/损坏备份/Focus 草稿 | 键加 owner 命名空间；无主历史键隔离，禁止自动归当前账号或重传；用户明确决定处理 |
| Rust offline.sqlite3（WAL/SHM） | 表加 owner 列 + 分区索引；无主行隔离；清真实 payload 非仅列表过滤 |
| SQLite 物理残留 | 全账号删除才 VACUUM；单源清理行级清除 + checkpoint，按并发锁实现；保留其他 owner 内容 |
| React/Zustand/query cache、搜索结果、临时材料 | 停在途请求后清内存；取消重连回调；防旧响应写回 |
| Stronghold 业务 token、campus session/cookies | 「清除账号数据」解释校园会话影响，清目标 owner 关联凭据；不同 owner 共用会话时先隔离或停自动复用 |
| 上传/下载临时文件、应用生成的导出副本 | 应用控制路径枚举清理；用户指定外部目录不可宣称已清 |
| 本地删除标记/代际 | 不含正文，持久阻断旧队列；新登录先核 Backend 屏障/代际，明确重导入才恢复来源 |

本机导出附包含未同步草稿：**B 决定 M5 不实现**（账号删除路径本机全清，
导出+删除双流程的附包打包复杂度不成比例；alpha 后重评）——UI 必须明示
「Backend 导出不含离线未同步草稿」；未同步队列删除会丢未提交工作，在本机
清理确认中明确提示。源删除按 Backend 抑制状态清该来源队列；客户端不是
权限判定者。旧客户端无代际、设备长期离线、重新采集上游相同事件都进 E7。
新同账号合法数据不得因全局缓存清理误删；账号删除后重新注册视为新 owner，
不自动认领旧资料；同 owner 无关旧草稿可明确确认重基并由 Backend 逐项
校验，不为恢复合法草稿自动把整个旧队列标成新代际。

## 5. grant 面板与类别文案

复用 GET /v1/permissions/policy、GET/POST /grants 与 DELETE /grants/{id}，
显示 active/expired/revoked、作用域值、expires_at（有值显示到期，不自动
续）、授权与撤销时间。后端现对 active grant upsert——**扩大 scope 不能
藏在保存偏好动作里**。提案：grant 加 version/expected_version，新建/扩大
前显式确认，缩 scope/撤销即生效；旧 grant 迁移与 scope catalog 由 A/
协调人冻结。空态文案：「当前没有自动执行授权——所有需要确认的动作仍会
先问你」（无 grant 不影响 L2 功能）。

**GrantScopeCatalog 端点形状提案**：`GET /v1/permissions/scope-catalog` →
`{catalog_version, actions: [{action, level, implemented, categories[],
channels[], supports_time_window}]}`。客户端按目录渲染可授权项，未知
action/category/channel fail-closed 不显示；**catalog_version 变更纪律**
（A 互审建议 3）：服务端新增/变更 action、channel 必须升版本，客户端按
版本缓存失效重取——目录不成为第二个 drift 面。与现行 policy API 的关系 =
policy 保留通用说明面，catalog 是**值级新面**（现 policy description 不能
替代）。实际 dispatch 复验类别 AND 渠道（E6 实证 strict_scope_validator
要求双显式）AND 可选时间窗。

| 类别/概念 | 文案与边界 |
| --- | --- |
| notify.push / replan | 「计划偏差提醒：在你授权的类别与渠道内自动提醒」；现只有 replan 生产者，不添加未实现的 deadline/email/calendar 选项 |
| channels | 必须显示具体支持渠道；现代码只结算 delivered，不足以证明 OS/远程推送。先冻结实际渠道枚举/执行路径，未知渠道拒绝，而非展示「手机推送已授权」 |
| local_time_window | 执行校验未冻结前不给配置入口；若支持必须拒绝越窗执行，不能只存字段 |
| daily_budget/quiet hours | 打扰上限与静默规则，独立于 grant；daily_budget=3 暂留（自愿 Alpha 反馈后裁定）；category 启用 ≠ L3 授权 |
| model_context_consent | 「允许将选定个人上下文发给模型」，不授予自动修改/发送权限；与课程 grounding 同意独立 |
| L2 动作 | 每次确认任务/计划/Focus/写 Memory；L3 通知授权不覆盖这些动作或永久删除 |
| 撤销 | 「停止此授权下尚未发出的自动动作」；已发通知不能收回，结果不明诚实列状态 |

scope 仍严格 categories/channels：空值/通配/未知键拒绝；旧不合规 grant
标注需重新授权，不自动扩成通配。以上均为待裁定契约增量。

## 6. 同意、许可与客户端可观测

数据说明用 A 稿四问表生成用户可读清单：上传什么、本人/服务访问、保留
多久、删除范围；不扩大新数据采集。技术 trace 默认脱敏：campus 仅
host 类别/步骤/时长/安全错误码，不传 URL 参数/cookie/原始响应；campus
span 是本地 span，仅用户同意后上传；客户端日志/异常/崩溃报告同口径检查；
未决定保存期就不启外部错误服务。

**许可盘点交付物（B 主责）**：`THIRD_PARTY_NOTICES.md` + 逐文件出处表
（vendor/onethu/core、info-lib 认证子集、移植到 apps/desktop 的派生代码：
source SHA、适用许可/例外、适用主体、保留声明、source/binary 分发结论、
未澄清项）；A 核构建/SBOM/npm 依赖侧。OneTHU 非商业条款、BSL 1.1、
LearnX 例外分别审，不假定 OneTHU 作者授权延伸至 Agenthu；**阻断规则：
未澄清 → 不发布二进制**（P0-6 发布门）；需另取授权或替换则单列任务，
不由本稿虚构法律结论。

## 7. 验收与测试

离线测试（jsdom + AppServices 注入 fake backend，M4 视图族模式）覆盖：
字段镜像/状态文案、重复确认锁定、stale preview、能力交付丢响应、换账号/
旧闭包/坏队列/corrupt 备份、清理状态机失败路径、grant scope 与撤销竞态。
E7-7 客户端准备清单：双 owner 隔离断言、corrupt backup fixture、
WAL 真实清除证据（verified 需真实清除而非列表过滤）、离线设备 pending
标注。Windows 重建 exe/dist 后 E7 双轮；无实现前不提交镜像实现的占位
测试。当前 r2 待 A 互审 + 协调人裁定，所有契约增量以冻结版为准。

## 8. r2 修订账（供 A 互审逐条对照）

**改错（3）**：
1. §2 确认幂等键 r1 写「mutation/client_request_id」——mutation_id 是 M4
   pending-action 词汇；删除/导出幂等键 = (user, kind, client_request_id)。
2. §2 FAILED 行 r1「联系操作者所需 request-id」含混——排查凭据是
   operation id（业务）与 request-id（信封），两者都列。
3. §4 r1 只列「SQLite 队列」未分层；实测为**三层**：TS localStorage
   （`agenthu.event-queue`/`.corrupt` 保留原 payload/`agenthu.focus-draft`）、
   Rust `offline.sqlite3`（lib.rs QueueDb，含请求 payload 用户内容面）、
   Stronghold 具名槽——矩阵按层重写，VACUUM 分级（全账号才做）。

**收紧（1）**（r1 无整段删除；按 A 互审建议 5 与「删除」措辞区分）：
「任务重查不重新创建包」明确为幂等三元组语义，避免读成前端缓存。

**补己见（10）**：Zod `.nullable()` vs `.optional()` 按 `?` 语义代码化 +
恒发字段同批 sequencing；preview_digest 不透明回显；recover 三输入要求
客户端留存 client_request_id；poll 参数提案（5s→30s 退避、30 分钟上限、
后台暂停）；本机清理状态机显式化 + 清除顺序；owner_key 构成与
EventSyncCoordinator 相容性；导出附包 defer 认领（B 决定 + 理由）；
GrantScopeCatalog 端点形状 + 与 policy API 关系；grant 空态/expires_at
展示；许可盘点交付物形状 + 未澄清阻断发布规则。

**同步（@A-r2 `581606a`，A 互审 §5/§6 采纳）**：① retry 输入收为
`expected_version` 单字段，镜像同步（§1）+ 409→重取 与 M4 confirm 同构；
② 账号删除状态查询走 receipt 轮询、手动重试仅 source/memory（§2）；
③ 旧客户端保留旧 DELETE 入口原语义（§1）；④ catalog_version 变更纪律
（§5）；⑤ verified 判据 = 可复跑检查命令输出（§3）；⑥ recover 留存完整
请求体参与摘要匹配 + receipt 视图统一「回执不可用」文案（§2）。
