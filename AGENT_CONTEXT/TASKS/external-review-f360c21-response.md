# 外部审查（main @ f360c21）回应任务书：审计结论与队列重排

Status: **协调人审计完成 + 队列重排落字（2026-10-09 深夜）。外部报告
21 项抽核全部坐实、零误报。E7 双轮顺延至 R1–R3 修复轮 + NOTICES
对账之后（§5）；原派工（m5-e7-execution.md）的通道裁定与协议不变，
仅执行时点后移。**

审计对象：外部模型对 `origin/main @ f360c21` 的只读审查报告（2026-10-09，
7 项 P1 + 30 项 P2 + P3 清单；报告本体含敏感事实描述，**不入仓**，存
于协调人侧桌面，本任务书按编号引用）。f360c21 → 5e90b33 仅文档差异，
代码结论对当前 main 等价成立。

## 0. 审计方法与总结论

协调人对全部 14 项 P1 + 7 项队列敏感 P2 逐项在 `git show f360c21:<path>`
锚点下独立复核（计数、行号、机制链），**21/21 坐实、0 误报、0 位置
漂移**。报告的横切模式判断（不变量只接部分入口；测试通过 ≠ 性质成立；
客户端信任边界弱于后端；不可逆操作失败路径系统性偏弱）与复核所见一致，
采纳为修复轮的组织原则。

数字出入一处（不影响结论）：报告规模行称 491 个 pytest 用例，CI 实测
（f360c21，run 37946355247）为 497+6=503——静态收集与运行态计数口径
差，以 CI 日志为准。

## 1. 逐项审计结论（复核过的才进修复队列）

### P1（14/14 坐实）

| # | 缺陷 | 复核锚点 | 队列去向 |
| --- | --- | --- | --- |
| 1 | grounded 问答无模型上下文同意门 | material_answers.py 0 处 consent 引用；grounded_answers.py:214-217 拼 L1/L2 正文、:332-333 检索；门只在 agent_tools.py:217 + context_assembly.py:190 | **R1-A** |
| 2 | 仓库 fixtures 含真实学号/VIEWSTATE PII | 三 fixture 各含 1 处 `你好, <10位学号>` 形态；VIEWSTATE 在场（1705/1325/6433 字符）；kongjian.smoke.mjs 实加载 | **R1-B（最急）** |
| 3 | 校园密码登录成功后无限期驻留渲染进程 | tauriAuthGateway.ts:186 赋值、:333 logout 唯一清空；finally 只清 helper.password；silentReloginCredentials 原样供应 | **R1-B** |
| 4 | 部署默认 ENVIRONMENT=local 关掉弱密钥防线 | compose :92/:140 默认 local；config is_local early-return；.env.example local+弱 key。缓和：compose 注释自认 dev 栈、无生产变体 | **R3-A** |
| 5 | 删除流自身的审计行逃过 redact（冻结 id 列表接不住闭包后产生的行） | data_operations.py:210-221 冻结 ids；middleware call_next 后写行；与 D-036「审计族 redact in place + 90d TTL」设计意图脱节 | **R2-A（E7-5 面）** |
| 6 | 证据链记忆逃删除闭包（keyed L2 source_event_ids=[]、血缘只进 evidence） | data_closure.py:344-355 仅交集判据；memory_lifecycle/event_handlers 写空 source_event_ids；GIN 索引 ix_memories_evidence 零使用 | **R2-A（E7-3/4b 面）** |
| 7 | FAILED 账号删除永久锁死（is_active 即时置假 + sweep 不收 FAILED + 拒绝手工重试） | data_operations.py:481；worker/tasks.py sweep 只收 QUEUED/RETRY_WAIT/陈旧 RUNNING；data_executor.py:530-544 显式拒绝 account 域 | **R2-A（E7-2/6 面）** |
| 8 | 拆块任务重复计账污染估时学习 | event_handlers.py:292-305 每项 COMPLETED + 每项累加整场时长；estimates 逐项采样 | **R3-A** |
| 9 | 超长 envelope 永久卡死同步批（dedupe 键 >255 → 整批回滚 500） | events.py 计算无长度上限；models/event.py:44 String(255)；批循环只捕 SuppressedSource | **R2-A（E7-7 面）** |
| 10 | 打包后查看删除回执必被 CSP 拦（未注入 backendFetch） | ReceiptViewer.tsx:36 未传 fetcher；data.ts:43 默认全局 fetch；正确模式在 services.tsx:57 | **R2-B** |
| 11 | 通配授权可落库并被 fnmatch 当模式 | schemas/permission.py:13 自由串；创建面无 ACTION_POLICY 校验；services/permissions.py:126 grant 侧即模式 | **R3-A** |
| 12 | 幂等键用进程随机 hash() | agent_tools.py:654、:702 | **R2-A（顺手同文件）** |
| 13 | 租约心跳零调用点，长 run 双执行 | heartbeat_run 仅定义 :98 + __all__ :1504；reclaim 结算无 claim_token 守卫 | **R2-A（E7-5 面）** |
| 14 | 采集部分失败被 catch(()=>[]) 吞掉 | client.ts:704-716 逐 course×kind 吞错仅 debug 日志 | **R3-B** |

### P2 抽核（7/7 坐实）

写守卫 events 入口 0 接线（16 处其他面在案；**与 CURRENT_STATE
「§2.3 全面接线」口径冲突，R2-A 对账修文或修码**，去向 R2-A）；
Rust owner 全信任（queue_*/focus_* 无校验，R2-B）；unowned_adopt 缺
self 守卫（focus 兄弟函数有，R2-B）；漂移检查签名无 security 字段
（R3-A）；DB 不可达 → session skip → 绿（R3-A）；FocusView 跨账号
残留 + 401 不清缓存（R3-B）；（P1-3 补核：credentials 仅 logout 清，
坐实）。

### 待核（不进本队列）

P2 报告标注项（#17 死代码/VENUE_SIGN_KEY/i_pass 分支/NOTICES 三处
口径互斥、#20 确认栅栏死代码、#21 TOCTOU、#23 pip-audit 不同源、#24
容器姿态、#30 队列键弱化）与全部 P3：按「复核过才修」纪律，由归属
开发者在触碰对应模块时先行自证再修；#17 的 NOTICES 口径互斥部分提
前为 **NOTICES 吸收的前置对账项**（§4）。

## 2. R1 — 隐私急修（立即，并行，小 PR）

- **A**（#1）：grounded_answers 取记忆前判
  `active_consent_version(session, user_id) is not None`（与
  agent_tools.py:217 同源）；钉子测试「同意关 ⇒ provider 请求体不含
  memory.content」。E7-8 同意面语义不变（门只加不撤）。
- **B**（#2，最高优先）：三份 kj_*.html fixture 以合成学号/姓名/房号/
  VIEWSTATE 重生成（保留解析相关的 DOM 结构），清 saved-from-url 注释；
  验收 = kongjian.smoke.mjs 绿 + 全仓 grep 无真实形态残留（验收扫描
  命令入 PR 描述，不含样本值）。
- **B**（#3）：登录链成功 settle 时清 `this.credentials`（或显式墙钟
  过期并被 silentReloginCredentials 尊重）；回归覆盖「settle 后静默
  重登不再有内存凭据可供应」两分支。

## 3. R2 — E7 阻断面（A 后端 / B 客户端）

- **A**：
  - #6：删除闭包并入 `evidence @> '[{"type":"event","id":…}]'`（走
    已建 GIN）+ memory→memory 血缘不动点遍历；**E7-3/E7-4b manifest
    预期随 PR 同步修订**（预登记纪律）。
  - #5：审计族 redact 由冻结 id 列表改为执行期扫描（owner 谓词或
    `created_at >= preview.created_at`），对齐 D-036「redact in place +
    90d TTL」设计；E7-5 预期同步。
  - #7：**预裁方向**——confirm 仍即时停用（E7-2「停用后仅窄 receipt
    路径」语义保持），FAILED 的 account 操作增加 capability-token
    驱动的重排入口（复用回执窄路径），不引入无限流手工面；A 细化后
    若推翻预裁需回协调人。
  - #13：循环内心跳 + 结算走条件更新（claim_token 谓词）；E7-5 双
    worker 断言面受益。
  - #9：dedupe 键长度检查入逐 envelope 拒绝链（与 suppression 同级，
    单条拒绝不炸整批）；#12：hash() 换 _args_hash 同款 sha256。
  - 写守卫 events 入口接线（或对账修正 CURRENT_STATE 口径——二选一
    落 DECISIONS）。
- **B**：
  - #10：ReceiptViewer 注入 `isTauriRuntime() ? backendFetch : undefined`
    + 打包路径回归（CSP guard 形态）。
  - Rust 三连：queue_*/focus_* 的 owner 参数过 `receipt_owner_valid`
    同源校验；unowned_adopt 补 self 守卫；owner 迁移包显式事务（消除
    RENAME/INSERT 间崩溃窗口）。

## 4. R3 — 控制面与余量（E7 前收尾）

- **A**：#18 漂移签名加 `security`（丢 CurrentUser 必须红）；#22 CI
  最小通过数闸门（或 skip 上限，防「全 skip 绿」）；#4 生产 compose
  变体（或默认翻转 + 本地 override，fail-closed 防线至少在一个被执行
  形态上生效并测过）；#8 完成写入限定最接近会话时刻的项（或分摊）；
  #11 grant 创建校验 action ∈ ACTION_POLICY 键集并拒 `* ? [`。
- **B**：#14 采集失败计数 + partial 标记透出 UI；#26/#27 登出卸载或
  清空已挂载视图态 + 401/换号清查询缓存（含 owner 维度键改造评估）；
  #28/#29 顺手；**#17 前置对账**（NOTICES/LICENSES/THIRD-PARTY 三处
  口径 + cookie 镜像声明 vs 实况 + 死代码上游面清单）落档供 A 吸收。
- **A（NOTICES 吸收，R3 后、E7 前）**：以 license-inventory §7/§8
  为清单源吸收 THIRD_PARTY_NOTICES.md，**必须先解 #17 对账结论**，
  三处口径归一后落笔。

## 5. E7 门序修订

E7 双轮（通道裁定、协议、E7-10 三分项均不变，见 m5-e7-execution.md）
**顺延至 R1–R3 + NOTICES 吸收全部合并后**执行；执行 head = 届时
main HEAD。理由：#5/#6/#7/#9/#13 恰在 E7-2/3/4b/5/7 断言面上，先跑
双轮等于花两轮重发现已知缺陷；修复轮内 manifest 预期随实现同步修订
（D-036 实施令沿用），双轮在修正后的语义上一次性取证。

## 6. Backlog（M5 收口后）

P2 待核余项（#20/#21/#23/#24/#30）与 P3 全清单按模块就近批量清；
每项修前按本任务书 §1 同标准自证（复核过才修）。报告「需实测」节
（桶版本化、部署拓扑、GBK 影响面、keyring 漫游、GitHub required
status）转 E7 执行轮与部署演练的观察项。

## 7. 决议记录

- 2026-10-10 用户裁定（⑤，随 #2 交付上浮）：git 历史中的真实身份数据
  **维持不动、不改写**——暴露窗口由裁定②封顶（临时公开、完毕即关闭，
  关闭即历史终结）；终局关闭前如需再评，由用户届时发起。已落 PR #90
  评论与 DECISIONS。
- 2026-10-09 协调人：外部报告审计 21/21 坐实采纳；队列重排为
  R1（隐私急修）→ R2（E7 阻断面）→ R3（控制面+余量+NOTICES 对账
  吸收）→ E7 双轮 → M5 收口；E7 派工时点后移、内容不变；#7 修复
  方向预裁为 receipt 窄路径重排入口。
- 2026-10-09 R1-A 执行（#1，PR #91，分支 `fix/grounded-consent-gate`）：
  grounded_answers 取记忆前判 `active_consent_version`（与 agent_tools
  同源）；同意关 ⇒ 请求体无 memory.content、回执 `memory_ids=[]`；钉子
  测试双向断言（关⇒不含/开⇒原语义恢复），两处既有记忆断言测试补全局
  同意前置。E7-8 同意面语义不变（门只加不撤）。
- 2026-10-10 R2-A 执行（#7，分支 `fix/account-requeue-receipt`）：按预裁
  落地——confirm 即时停用不动（停用后业务面 401 语义不变），FAILED/
  RETRY_WAIT 的 account 操作经回执窄路径重排：`POST
  /receipts/{id}/requeue`（Authorization capability，缺/错/未知统一
  404；有效键得真实态 409 version_conflict / not_retryable）。
  `requeue_account_operation` 与 source/memory 手工 retry 共享
  `_reset_operation_ladder`（FAILED/PENDING 项新梯、DONE 进度保留、
  QUEUED 归队交 sweep 再派发；account barrier 不动）。回执读面增
  operation_status / operation_version（窄路径持有者取乐观版本的唯一
  来源；openapi 再生成 71 路径）。钉子 ×5：FAILED 复活全断言 / 错键
  统一 404 / COMPLETED 永不复活 / 版本冲突 / 回执暴露状态与版本。
  E7 预期无变动（重排为新增能力，未触任何既有断言；预裁未推翻）。
