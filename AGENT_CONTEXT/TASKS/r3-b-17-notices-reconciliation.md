# R3-B #17 前置对账：NOTICES 三处口径 + cookie 镜像声明 + 死代码上游面

Status: **对账完成（2026-10-10，B 执行）。证据全部锚定 `origin/main @ 22ec867`
（R2 全合后的 docs-only 头；代码面对 `17eccc0` 等价——两者仅 CURRENT_STATE
差异）。本档只对账不修文：THIRD_PARTY_NOTICES.md / VENDORED_FROM.md /
vendor notices 的落笔归 A 的 NOTICES 吸收轮，死代码去留归协调人裁定。**
外审 #17 三项（NOTICES 三处口径互斥、cookie 镜像声明 vs 实况、死代码上游面）
逐项复核：前两项**坐实且比报告更具体**，死代码面五项中四项钉锚、一项
（#20 确认栅栏）仓内证据无法独立定位，如实标注待锚。

## 0. 边界与方法

- **对象**：①三处口径面 = 根 `THIRD_PARTY_NOTICES.md` / `vendor/onethu/{LICENSE,
  VENDORED_FROM.md, LICENSES/THIRD-PARTY.md, info-lib/LICENSE}` /
  `AGENT_CONTEXT/TASKS/m5-p0-6-license-inventory.md`（§2.1/§2.2/§7/§8 普查）；
  ②根 NOTICES 尾行 cookie/凭据声明 vs 实现实况；③死代码上游面清单。
- **不负责**：不改任何 license/notices 文件本体；不删死代码；不做 A 的
  吸收落笔。
- **方法**：全部结论带文件:行锚点，`git show origin/main:<path>` 实读 +
  `git grep` 全仓实测；与普查 §2.1/§2.2 的实测记录交叉印证，不重复测量
  普查已测面（desktop 引用面、bundle 内含物沿用普查数字）。

## 1. NOTICES 三处口径互斥清单（坐实）

### M1 — info-lib 谱系：根 NOTICES 整节描述路径 B 之前的树（最重）

根 `THIRD_PARTY_NOTICES.md` "OneTHU info-lib authentication subset" 节宣称：

1. **Source / Pinned commit** = OneTHU `2e3455f…`（"Source: …smartThise/OneTHU,
   Pinned commit: 2e3455f…, Vendored at: vendor/onethu/info-lib"）；
2. "License and notices: retain the upstream MIT, **BSL 1.1**, LearnX and
   dependency notices…"；
3. "**The BSL 1.1 boundary applies to the copied authentication sources**
   where identified by the upstream notices"。

实况（两处同源佐证）：

- `vendor/onethu/info-lib/LICENSE`（路径 B 后的现态）三段声明：基座
  **2026-10 从 thu-info-app `06dc3cf0`（MIT 期最后快照）重推导**（error.ts、
  strings.ts 常量、core.ts 结构基座）；其上为本仓自有 MIT 作品
  （network.ts 重写、SM2/OAuth/TOTP/finger3 适配、login-chain reset 等）；
  测量记录指 `m5-p0-6-path-b.md`。
- 普查 §2.2 头注：**2026-10-08 路径 B 已执行**，"四文件已从 `06dc3cf0`
  MIT 基座重推导 + OneTHU 适配层平移 + 活面协议独立实现，LICENSE 已改
  真话"；节内旧谱系表（v3.17.0/BSL 实测）**保留作依据、不再描述当前树**。

**互斥判定**：根 NOTICES 该节三句全部失实——info-lib 的来源不再是
OneTHU@2e3455f 的拷贝（而是 thu-info-app@06dc3cf0 基座重推导 + 自有层）；
"BSL 1.1 boundary applies to the copied authentication sources" 所指的
BSL 谱系拷贝在路径 B 后**已不存在于树内**。BSL 面的事实迁到了历史记录
（普查 §2.2 保留表 + path-b 任务书），不再是对当前树的许可描述。

### M2 — LearnX 移植宣称：根 NOTICES 与普查实测相反

根 NOTICES "OneTHU dependency and project notices" 节：
"OneTHU core contains code **identified by upstream as ported from LearnX**,
whose additional exception terms are recorded there."

实况：普查 §2.1 learn 行实测——**本树无任何 learnX 移植标注**（grep 唯一
learnx 字样在 coursex，且 coursex 文件头自证"仅接口结论验证"，上游分类法
第 3/4 类，不构成代码拷贝）。

**互斥判定**：对 **Agenthu vendored 子集**而言"contains ported code"为
假。上游 THIRD-PARTY.md 对 OneTHU 全库的 LearnX 移植识别是上游自己的事实
（对其全库为真），但根 NOTICES 把它复述为本树状态即为失实。防御性保留
LearnX 例外条款记录是合理的，事实句必须改。

### M3 — VENDORED_FROM.md 只覆盖 core，info-lib 现状无档

`vendor/onethu/VENDORED_FROM.md` 只写 `packages/core`（@onethu/core 0.8.0）；
info-lib 的路径 B 后谱系只存在于 `info-lib/LICENSE` 与 AGENT_CONTEXT 任务书。
上游 `LICENSES/THIRD-PARTY.md` §1 "Vendored 基线：上游 3.17.0" 描述的是
**上游自己的 vendoring**（该文件为上游原样保留，本身无误），但 vendor 目录
内没有任何面向读者的文件指向"本树 info-lib 已于路径 B 重推导"——读者从
VENDORED_FROM.md/THIRD-PARTY.md 出发会得出与 LICENSE 相反的谱系结论。

**互斥判定**：VENDORED_FROM.md 缺 info-lib 现状节（遗漏型互斥，非错误句）。

### 一致项（免改）

- 邮件授权"点名 OneTHU、未言明延伸至 Agenthu"——根 NOTICES、THIRD-PARTY.md
  §1、普查 §1.2 三处一致 ✓。路径 B 后该授权对 info-lib 的**必要性**下降
  （基座全 MIT），但"不得假设延伸"的警示仍正确。
- core 面"OneTHU MIT + 附加限制、不得描述为无限制 MIT"——三处一致 ✓。
- 根 NOTICES 的源码临时公开语境（裁定②）与 README a70f7e2 一致 ✓。

## 2. cookie 镜像声明 vs 实况

**声明原文**（根 NOTICES 尾行）：
"Agenthu does not copy credentials, cookies, or upstream raw responses
into Event payloads or logs."

**逐面实测**：

| 面 | 实况 | 与声明关系 |
| --- | --- | --- |
| Event 载荷 | 事件构建面零 cookie 字段（`apps/desktop/src/adapters/campus/events.ts`、`onethuAdapter.ts` grep 零命中；envelope 为 type/occurred_at/source/data/context/provenance） | **成立** |
| 镜像本体 | `cookieMirror.ts` 实存：`campus_request` 回传的 `*.tsinghua.edu.cn` host/name/value/hostOnly **三元组跨 IPC** 进渲染进程内存 Map（`buckets`），供 vendored InfoClient 的 XSRF 读取与 wengine dance 注入；请求附 Cookie 头仍由 Rust 每跳完成（`runtime.ts:24-30` 只读镜像 jar 接线） | 声明字面说"不拷进 payloads/logs"，**未提镜像存在**——读者会理解为 cookie 不出 Rust 仓；实况是**受控最小投影**（campus host、无 Expires/HttpOnly 等属性、不持久化 `serialize:()=>\"[]\"`、logout `jar.clear()` 同步清） |
| 日志/调试通道 | debug 通道（默认关，`runtime.ts:30`）落 DevTools 前过 `redactCampusDebugLine`：`name=value` 形态且值 ≥20 字符遮蔽为 `<redacted>`，超长行截 4000 | 值**基本**不落日志；**残留缺口**：<20 字符的短值（若以 `name=value` 形态出现在诊断行）不会被遮蔽。声明用的是绝对句式 |

**对账结论**：声明两处需要精确化——①补镜像存在与其边界（campus host 三元组、
内存态、不持久化、随 logout 清）；②日志句从绝对式改为精确式（值 ≥20 字符
遮蔽；短值残留缺口要么如实写、要么把遮蔽规则放宽到全部 `name=value` 形态——
后者是代码改动，超出本对账轮，列为吸收轮可选项）。

**凭据面**（顺带核）：校园账密生命周期 = Rust vault + 网关内存，settle 即清
（#92 `tauriAuthGateway.ts` settle 点 `this.credentials = null`）——声明对
credentials 成立 ✓。

## 3. 死代码上游面清单

> 「上游面」= 引用/复刻上游（OneTHU/thu-info）系统接口的死代码——它们不出
> 现在 Agenthu 运行路径，但留在源码树随仓分发。去留需裁定（删除影响上游
> 同步成本；保留则每次谱系审计都要重新解释），本档只列事实。

- **D1 `vendor/onethu/core/src/venue/sign.ts` + `index.ts:204` 再导出**：
  `VENUE_SIGN_KEY` 硬编码（:82）+ `buildVenueSign`/`venueSignQuery`（:97 组串
  签名）。desktop 引用 **0**（普查 §2.1 venue 行）、bundle 实测排除（§5-2）。
  这是**自动预约提交能力面的签名构件**——附加限制②点名禁用用途，源码面
  在场即需在每次分发审查中重新论证。红线关联：二进制/UI 不得暴露 venue
  提交面（现状成立）。
- **D2 `vendor/onethu/core/src/auth/cas.ts` 的 `submitCasLogin`（:136）+
  `fetchCasForm`（:127）**：全仓零调用（定义 + `index.ts:24-25` 再导出外无
  引用）。函数内含外审点名的 **i_pass 双写分支**（:144-156：WebVPN 层
  `{i_pass: \"\"}` 空写 + sm2pass；直连层 `i_pass: enc` + `sm2pass: enc` +
  singleLogin）。**i_pass 字段集本身是活的**——活路径为 info-lib login
  （path-b 重推导，`i_pass = \"04\" + sm2.doEncrypt(...)`）与 InfoClient
  内联直连 id 重登（`info/client.ts:2085-2097`：直连层自写 `i_pass: enc`，
  zhjwxk 变体加 sm2pass+singleLogin；`parseCasFormHtml` 被 client.ts:2079 与
  zhjwxk/client.ts:309 实调）。**判定：报告所指死分支位于死函数内；表单解析
  系活件，表单提交包装层是死件。**
- **D3 `vendor/onethu/core/src/auth/demoLogin.ts`**：`session.ts:10` 退役记录
  在案（"demoLogin 全链…退役"）；残存引用只有 `exthw/tuojCas.ts:77/:294`
  的注释类比与 `info/client.ts:1560` 的历史注释。
- **D4 普查 §2.1 已测的 vendored 未引用模块面**（沿用普查，不重测）：
  `coursex`/`caldav`/`exthw`/`privacy` 整模块 desktop 0 import（源码树随仓
  分发）；`zhjwxk` 直接 import 0、`fetchZhjwxkPage` 经 InfoClient 兜底进
  bundle（只读 GET），**提交类函数与 xkAction 路径 0 命中**（红线成立依据）。
- **D5 外审 #20「确认栅栏死代码」：无法独立钉锚**。仓内核查：DataBarrierScope
  三 scope（ACCOUNT/SOURCE/MEMORY）全活（raise/matching/release 链在
  data_operations/data_lifecycle/write_guards 实调）；pending_actions/plans/
  permissions 的 confirm 面无定义在案的未调用栅栏构件。**未复核 → 不列
  事实**：需协调人从外审报告（桌面副本）提供原始锚点后补入本档附录。

## 4. 供 A 吸收轮的落笔建议（非终稿文案）

1. 根 `THIRD_PARTY_NOTICES.md` info-lib 节整节重写：来源改
   thu-info-app@06dc3cf0 基座重推导 + 本仓自有层（对齐 info-lib/LICENSE 三段
   声明）；"BSL 1.1 boundary applies…"句删除或改为历史注记（BSL 谱系拷贝
   已随路径 B 拆除，事实见普查 §2.2）；保留"邮件授权点名 OneTHU、发布前
   完成分发审查"警示。
2. LearnX 句改为事实形："上游 notices 将部分代码识别为 LearnX 移植；本仓
   vendored 子集经普查实测无移植标注（license-inventory §2.1），LearnX 例外
   条款记录保留作防御性披露"。
3. `VENDORED_FROM.md` 增 info-lib 现状节（一句话指 LICENSE 三段声明 +
   path-b 任务书即可闭合 M3）。
4. cookie/凭据尾行按 §2 精确化（镜像存在 + 边界 + 日志遮蔽规则现状）。
5. D1–D5 逐项去留裁定建议提交协调人：D1（venue sign 面）与 D2（cas 提交
   死件）删除可收缩源码面、但增加与上游 diff 维护成本，倾向**裁定后单列
   小 PR**，不入吸收轮；D5 待锚。
