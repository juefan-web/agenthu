# M5 B 草稿：数据控制、授权面板与本地生命周期

Status: **r1 提案，2026-10-05；待 B 修订、A 互审、协调人裁定**。
基线bf02eeb；任务边界见 [phase-0](m5-phase0-prereq-docs.md)。
Backend事实层不变；本机清理是客户端责任，不代表远程设备已清理。

## 1. API与页面责任

复用backend client/transport、packages/contracts、现Basis组件、
错误envelope、Stronghold与队列适配层，不在React执行删除业务规则。
入口“数据与隐私”连接现有资料/Memory/Chat删除入口，
“自动执行授权”连接grant，“模型数据使用”保留独立consent。

必须逐字段镜像 [A稿 §4](m5-data-lifecycle-ops-contract.md) 的
DataCapabilities、DeleteTarget、DataPreview、DataEffect、DataOperation、
OperationPhase、OperationProgress、SafeError、DataReceipt；
manifest消费 schema_version/graph_version/snapshot_at/generation/
family_counts/entries/excluded_categories。operation version必有，
nullable字段不能当可省略；receipt_capability只在创建/恢复交付，普通读取为null。
字段人工cross-review，Zod使用显式z.object，避免旧drift解析器漏.extend；
同时验证后端多字段被客户端strip、optional/nullable不符。

未具备capabilities时显示“此服务尚未支持完整导出/删除”，不能把旧204
渲染成全量擦除成功。业务401退出后仍可用独立receipt读取清理结果；
receipt能力从不放URL、日志、剪贴板自动复制或遥测。

## 2. 导出与删除流程/文案

导出：用户选择含文件（默认勾选）→提交一次client_request_id→显示操作
进度→READY才下载→到期禁下载。服务端含敏感全文，下载前说明本地副本
由本人保管；清客户端缓存不会自动擦除下载到任意目录的导出文件。
任务重查不重新创建包；丢202重传同ID，不每次点击生成新ID。

删除：选择账号/来源/记忆 →请求preview →显示服务端effects与limitations →
独立确认 →202进入“删除处理中” →查询receipt/operation →
确认受控在线清理完成，再显示本机清理及其他残留状态。
不能离线确认后偷偷恢复联网执行不可逆删除；离线只保存非敏感选择。
账号删除要求重新确认当前登录账号的可读身份和不可恢复后果；
用户可以先导出，但不能默认帮他导出。

| 状态/情况 | 用户可见行为 |
| --- | --- |
| preview | “将删除X项、清除Y项派生内容、重算Z项；独立编辑内容按清单保留”。不自己推断级联 |
| preview_stale/到期 | “数据已变化，请重新查看删除范围”；旧确认按钮失效 |
| QUEUED/RUNNING | “删除已提交，正在清理”；只用服务端phase/count，无虚构百分比 |
| RETRY_WAIT | “部分清理尚未完成，系统将在…重试”；显示剩余数和安全错误 |
| FAILED | “删除未完成”；提供同operation重试/联系操作者所需request-id，无敏感原文 |
| COMPLETED | “服务端在线数据已清除”；另列备份最晚失效时间、供应商说明、本机/其他设备待清理 |
| export READY/EXPIRED | “可下载至…”/“导出包已到期”；下载403/超时不能误称不存在 |
| source_deleted | 复用Basis失效展示；不保留quote/标题/摘要，不再跳转到已删来源 |

永久忘记Memory明确“含历史版本”；拒绝Memory仍是阻止再派生的不同动作，
不能把现REJECTED占位误称已永久擦除。Chat隐藏/归档和永久删除须分清，
说明隐藏内容的拟保留期；冻结改变旧删除按钮语义时同步文案与兼容策略。
资料删除preview明确回答/引用/派生Memory影响；撤销模型同意只停未来
发送，不伪称从供应商立即收回既有内容。

重复点击确认按钮锁定同一mutation/client_request_id。
409重取preview或版本，不后台自动扩大授权；429显示Retry-After；
未知状态停止危险操作并显示升级提示。页面poll有上限、退避和后台暂停，
手动查询只GET，不重发DELETE/POST。receipt恢复按A的10分钟特殊路径，
失败也告知“清理仍在继续，回执凭据未能取回”，不能重新开启账号。

## 3. 回执与本机清理状态

账号确认成功后马上停采集/同步/poll/run请求，清业务JWT与query cache；
receipt capability保存在独立Stronghold槽位，仅限回执、90天到期；
Web fallback仅内存，可显式导出脱敏回执文件，不将能力写localStorage。
回执与业务token不能一起误删导致进度不可见。

local_cleanup_required是服务端提示，本机另维护：
not_started/cleaning/verified/failed；其他设备是unknown/pending，
没有设备响应时不能猜verified。服务端COMPLETED不等于本机verified。
本机清理失败仍冻结旧队列，允许明确重试本机清理；不能返回采集/同步。
显示backup_expires_at与provider_limitations，不声称供应商零保留。
用户导出的外部副本、无法在线控制的旧设备均明确说明。

## 4. 本地存储、账号隔离与防复活

现LocalEventQueue及SQLite pending_events/sync_state/focus_draft没有owner维度；
M5必须先修此边界，不能只queryClient.clear()。
命名空间以canonical backend origin + server user_id构成，
data_generation独立保存并用于同步。相同校园账号不等于同Backend账号。
登录/切账号时取消旧请求与sync循环，后台闭包也不能沿用新token提交旧队列。

| 储存/副本 | 清理与迁移 |
| --- | --- |
| SQLite队列、游标、Focus草稿 | 增owner分区；无主历史行隔离，禁止自动归给当前账号或重传；用户明确决定处理 |
| SQLite损坏行/WAL/SHM/备份 | 不仅list过滤；清真实payload。安全删除/检查点/必要VACUUM，按并发锁实现；保留其他owner内容 |
| localStorage队列与corrupt backup、Focus fallback | 清对应命名空间和旧未归属隔离副本；不只删除主key |
| React/Zustand/query cache、搜索结果、临时材料 | 停在途请求后清内存；取消重连回调；防旧响应写回 |
| Stronghold业务token、campus session/cookies、指纹关联 | 本机“清除账号数据”解释校园会话影响，清目标关联凭据；不同owner共用会话时先隔离或停止自动复用 |
| 上传/下载临时文件、应用生成导出副本 | 应用控制路径枚举清理；用户指定外部下载目录不可宣称已清 |
| 本地删除标记/代际 | 不含正文，持久阻断旧队列；新登录先核Backend屏障/代际，明确重导入才恢复来源 |

本机导出若包含未同步草稿，作为用户显式可选的独立附包，
注明“未被Backend确认”，不混入云端manifest事实层；M5 r1建议先不实现附包，
UI必须说明Backend导出不含离线草稿。未同步队列删除会丢尚未提交工作，
在本机清理确认中明确提示。

源删除按Backend抑制状态清该来源队列；客户端不是权限判定者。
旧客户端无代际、设备长期离线、重新采集上游相同事件都进E7。
新同账号的合法数据不得因全局缓存清理误删；账号删除后的重新注册视为新owner，
不自动认领旧资料。同owner无关旧草稿可明确确认重基并由Backend逐项校验，
不能为了恢复合法草稿自动把整个旧队列标成新代际。

## 5. grant面板与类别文案

复用GET /v1/permissions/policy、GET/POST /grants与DELETE /grants/{id}，
显示active/expired/revoked、作用域值、到期、授权与撤销时间。
后端现在对active grant upsert；扩大scope不能藏在保存偏好动作里。
提案：增加version和expected_version，在新建/扩大授权前显式确认，
缩scope/撤销即生效；scope catalog和旧grant迁移由A/协调人冻结。
不默认授予“所有行动”，不把action名称白名单当成所有工具都已实现。

| 类别/概念 | r1文案与边界 |
| --- | --- |
| notify.push / replan | “计划偏差提醒：在你授权的类别与渠道内自动提醒”；现只有replan生产者，不能添加未实现deadline/email/calendar选项 |
| channels | 必须显示具体支持渠道；现代码只结算delivered，不足以证明OS/远程推送。先冻结实际渠道枚举/执行路径，未知渠道拒绝，而非展示“手机推送已授权” |
| local_time_window | 执行校验未冻结前不给配置入口；若支持必须拒绝越窗执行，不能只存字段 |
| daily_budget/quiet hours | 打扰上限与静默规则，独立于grant；daily_budget=3暂保留。已有category启用也不代表L3授权 |
| model_context_consent | “允许将选定个人上下文发给模型”，不授予自动修改/发送权限；与课程grounding同意独立 |
| L2动作 | 每次确认任务/计划/Focus/写Memory；L3通知授权不覆盖这些动作或永久删除 |
| 撤销 | “停止此授权下尚未发出的自动动作”；已发通知不能收回，结果不明诚实列状态 |

后端建议提供版本化GrantScopeCatalog（字段：catalog_version、
actions[] {action, level, implemented, categories[], channels[], supports_time_window}），
客户端从目录渲染，未知类别fail closed；当前通用policy description不能替代值级目录。
scope仍严格categories/channels，空值/通配/未知键拒绝，实际dispatch复验
类别AND渠道AND可选时间窗。旧不合规grant标需重新授权，不自动扩成通配。
以上属于待裁定的契约增量，不能假定现API已具备。

## 6. 同意、许可与客户端可观测

数据说明用A稿四问表生成用户可读清单：上传什么、本人/服务访问、
保留多久、删除范围；不扩大新数据采集。技术trace默认脱敏，
campus仅host类别/步骤/时长/安全错误码，不传URL参数/cookie/原始响应；
客户端日志/异常/崩溃报告也检查。未决定保存期就不启外部错误服务。

B逐文件盘点vendor/onethu/core、info-lib认证子集、LICENSES以及移植到
apps/desktop的派生代码，写source SHA、适用许可/例外/主体、
保留声明、source/binary分发结论与未澄清项；A核构建/SBOM依赖。
OneTHU额外非商业条款、BSL 1.1、LearnX例外分别审，不假定OneTHU作者
授权延伸至Agenthu。未澄清阻止相应分发；如需另取授权或替换，单列任务，
不能由本稿虚构法律结论。

## 7. 验收与待审状态

测试覆盖字段镜像/状态文案、重复确认、stale preview、能力交付丢响应、
换账号/旧闭包/坏队列/SQLite WAL、清理失败、grant scope与撤销竞态；
Windows重建exe/dist后E7双轮。无实现前不提交镜像实现的占位测试。
当前无B署名批准/A互审记录，所有契约增量等待phase-0裁定。
