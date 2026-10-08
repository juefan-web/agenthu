# M5-P0-6 许可逐文件盘点（提前启动的清点阶段）

Status: **两实测动作已执行（2026-10-08）：§5-1 闭合结论不利——info-lib
四文件实测为 post-BSL（v3.17.0）派生，源码+二进制分发双双封印待
§5-6 路径裁决；§5-2 闭合红线全过。清点启动于 2026-10-07（#75 合并后，
协调人既有授权）；阻断规则：未澄清 → 不发布。**

依据：THIRD_PARTY_NOTICES.md（项目级骨架，已存在）、
vendor/onethu/{LICENSE,VENDORED_FROM.md,LICENSES/THIRD-PARTY.md,
info-lib/LICENSE} 全文（本轮全部重读）、vendored 树与 apps/desktop 的
grep/结构普查（数字为实测）。上游 pin：
OneTHU `2e3455fc235719b7f91fffaf5fe35e09220dda73`；
info-lib 上游仓 = <https://github.com/thu-info-community/thu-info-app>
（`packages/thu-info-lib`，两基线 `06dc3cf0` / tag `v3.17.0`）。

## 0. 边界

- **目标**：三大面（vendor/onethu/core、info-lib 鉴权子集、apps/desktop
  派生码）逐文件出处表 + 源码/二进制分发结论 + 未澄清清单。
- **不负责**：npm/cargo 全依赖机械普查（§5-3/5-4 列为后续动作）；
  上游 diff 验证（§5-1，动作已给出命令）；二进制构建内含物检查（§5-2）。
- **方法**：条款以随树许可文件为权威；代码出处以文件内标注 + import 面
  实测为准；"接口结论来源"与"代码移植"按上游 THIRD-PARTY.md 自有分类法
  区分（前者不构成代码拷贝）。

## 1. 条款结构（实测摘要）

1. **OneTHU 本体**（core 及 info-lib 中 OneTHU 自有部分）：MIT
   **+ 附加限制**——①严禁商业用途（含"接受与清华有关的机构对以本项目
   为交付物的项目的资助"）；②严禁对清华信息系统的攻击性/滥用性访问
   （点名抢课、占座、场馆/图书馆自动预约提交类插件脚本、规避风控限流）；
   ③违反即自动终止授权。**不得描述为无限制 MIT。**
2. **thu-info-lib（info-lib 上游）**：≤`06dc3cf0` 为 MIT；其后 BSL 1.1
   （Change Date = 版本首发满四年，Change License MIT）。THU Info 团队
   （孙迅）2026-09-16 邮件授权 OneTHU 非商业二次分发至 2036-12-31
   （授权对象**点名 OneTHU**，未言明延伸至 Agenthu）。
3. **LearnX**：MIT **+ 例外条款**——使用者（过去或目前）供职清华信息化
   技术中心、或项目接受任何清华关联机构经济资助 → 未经授权使用其代码
   （含复制/修改/再分发，无论是否商业）构成侵权。
4. **结论来源项目**（thu-tok-auto、yuketang-helper-auto、gpa.wtf）：
   MIT，仅接口结论验证，未取用代码。

## 2. 逐文件出处表

### 2.1 `vendor/onethu/core`（72 文件，54 .ts；`@onethu/core` 0.8.0，pnpm workspace 依赖打进桌面构建）

| 模块 | 文件 | 出处/许可 | desktop 引用 | 分发结论（源码/二进制） |
| --- | --- | --- | --- | --- |
| `src/auth`（CampusSession/登录态） | auth 模块 | OneTHU MIT+附加限制 | **是**（CampusSession/AuthRequiredError/login 流） | 随源码树与 bundle 分发；保留 LICENSE+附加限制全文；Agenthu 当前非商业、无滥用访问功能 → 一致 |
| `src/crypto`（SM2/WebVPN 密码学） | crypto 模块 | OneTHU MIT+附加限制 | 是（经 auth 路径） | 同上 |
| `src/info`（InfoClient：门户/校历/作业/课程文件） | info 模块 | OneTHU MIT+附加限制 | **是**（CalendarData/CourseFile/CourseInfo/Homework/ScheduleEntry import 实测） | 同上 |
| `src/learn`（LearnClient：网络学堂） | client/time/types/urls.ts | OneTHU MIT+附加限制；**本树无任何 `learnX 移植` 标注**（grep 实测唯一 learnx 字样在 coursex） | 是（requireLearnSession/csrfToken 路径实测） | 同上；上游 learnX 移植标注完整性 → §5-1 随上游 diff 一并闭合 |
| `src/coursex` | client.ts | OneTHU MIT+附加限制；文件头自证 **learnX 仅"接口结论验证"**（未取用代码，上游分类法第 3/4 类） | 否（未见 import） | 源码树分发；二进制理论上可摇树剔除（§5-2 验证） |
| `src/caldav`/`src/exthw`/`src/privacy` | 各模块 | OneTHU MIT+附加限制 | 否 | 同上 |
| `src/zhjwxk`（选课系统客户端） | client/gbk-table/xk-tab/xk-vol/anchor.ts | OneTHU MIT+附加限制 | **传递引用**（§5-2 实测修正：InfoClient `#crScheduleFallback` import `fetchZhjwxkPage`——夏季学期一级课表只读兜底，GET `kbSearch`，无提交面；直接 import 为 0） | 源码树分发；**bundle 实测部分进入**（fetchZhjwxkPage + 私有会话管道：ZHJWXK 常量/URL 前缀改写/anchor 正则/60s 热缓存）；提交类函数与 `xkAction` 路径实测 0 命中——附加限制②（抢课）红线在二进制面成立 |
| `src/venue`（场馆） | client/sign/types.ts | OneTHU MIT+附加限制；**附加限制②点名"场馆自动预约提交"为禁用用途** | **否**（desktop 无 import 实测） | 源码树随仓分发无碍；**二进制与 UI 不得暴露自动预约提交能力**——现状一致（未引用），摇树验证 §5-2；产品红线：切片 2+ 的数据控制页等任何 UI 不接入 venue 提交面 |
| `test/*.smoke.mjs` 等其余 | 测试/配置 | OneTHU MIT+附加限制 | 否 | 源码树分发 |
| npm 依赖 | `aes-js`、`sm-crypto`（core package.json 实测仅此两项） | 各自 MIT（随包保留声明） | 经 auth/加密路径入 bundle | 二进制分发保留其许可声明；全量机械普查 → §5-3 |

### 2.2 `vendor/onethu/info-lib`（8 文件，6 .ts；auth-only 瘦身版）

**§5-1 实测已闭合（2026-10-08，上游两基线三方逐文件 diff，方法与数字见
§5-1）**：四个上游派生文件全部为 **v3.17.0（BSL 期）谱系**，随树
LICENSE 的"`06dc3cf0` MIT 快照、post-BSL 不拷贝"声明**与事实不符**；
上游 THIRD-PARTY.md 的"Vendored 基线 3.17.0"才是实情。

| 文件 | 出处/许可（实测修正） | 备注 |
| --- | --- | --- |
| `LICENSE` | **声明失实待改**：自称基线 `06dc3cf0`，实测派生基线为 `v3.17.0`（BSL 1.1） | 改正文案随 §5-1 裁决路径（A 授权确认 / B 回退重推导）一并落 |
| `src/lib/core.ts`（472 行，InfoHelper） | **v3.17.0 + OneTHU 适配层**（48 行差全为自述适配：rtn-network-utils require 块剔除、finger3 响应修复、type import）；对 MIT 期基线差 242 行 | desktop import（login/roam/getCsrfToken/clearOutstandingLogin）实测——引用面 **4/6 在 06dc3cf0 基座**（login/roam/getCsrfToken/uFetch）+ `clearOutstandingLogin`/`setPlatformFetch` **随适配层平移**（两符号对两基座零命中、零上游谱系，OneTHU 自有新增，与 vendored LICENSE 自述的"其上新增为 OneTHU 自有"咬合；基座只有模块私有 `outstandingLoginPromise`）（回退路径 B 无功能损失） |
| `src/utils/network.ts`（136 行） | OneTHU 重写（对上游两基线差 336/475 行）；残留重叠偏 3.17.0 侧（common 51 vs 43） | 按 3.17.0 谱系从严归类 |
| `src/utils/error.ts`（107 行） | **与 v3.17.0 逐行相同**（0 行差；对 MIT 期差 4 行） | post-BSL 拷贝实锤 |
| `src/constants/strings.ts`（317 行） | v3.17.0 + 7 行 OneTHU 改动（对 MIT 期差 136 行） | 同 core.ts |
| `src/index.ts`（16 行） | **Agenthu 自写**（文件头首行 "Agenthu: auth-only interface" 实测） | auth-only 接口收窄声明 |
| `src/vendor.d.ts` | Agenthu 自写（sm-crypto 极小类型声明，仅 sm2.doEncrypt） | — |
| `package.json` | 元数据 | workspace: `@onethu/info-lib` |

**法律面（上游 v3.17.0 LICENSE 实读）**：BSL 1.1，**Additional Use
Grant: None**，Change Date = 该版本首发满四年（3.17.0 首发 **2026-09-15**
——commit `2026-09-15T06:02:04Z` 与 GitHub Release
`2026-09-15T06:22:52Z` 双源坐实 → **2030-09-15**；§1/§5-6 的邮件日期
2026-09-16 是另一事实，保留不混），Change License MIT。即裸 BSL 在
Change Date 前不覆盖 Agenthu 的任何分发；承重件只剩 THU Info 邮件授权
（点名 OneTHU、非商业、至 2036-12-31）——其对 Agenthu 链条的延伸性
= §5-6 现为**发布总门**。

### 2.3 `apps/desktop` 派生码面

- `src/adapters/campus/*`（onethuAdapter/tauriTransport/tauriAuthGateway/
  cookieMirror/events/index/runtime）：**消费型适配层**——import 面为
  类型 + 会话 + 数据读取函数（实测清单见 §2.1 引用列），未发现从
  OneTHU/learnX 复制的代码体；无 learnx 字样（grep 实测）。
- `src-tauri/src`（Rust 传输/Stronghold/SQLite）：onethu 字样仅为
  cookie/会话桥接注释，无上游代码拷贝（grep 实测）。
- 结论：**Agenthu 自有代码 + 以依赖方式使用 vendored 包**；二进制为
  vendored 代码与 Agenthu 代码的合并作品，分发结论见 §3。

## 3. 分发结论（§5-1/§5-2 实测后修订）

- **源码分发**（仓库/源码包）：**降级为受 §5-6 约束**——§5-1 实测
  证明 info-lib 四文件为 post-BSL（v3.17.0）派生，仓库分发本身即属
  BSL 意义上的再分发；在 §5-6（授权延伸确认，路径 A）或回退重推导
  （路径 B）落定前，**对外公开分发（含仓库公开化）暂停**；当前私库
  协作态维持。OneTHU 附加限制（非商业/禁滥用）继续适用且现状一致 ✓。
- **二进制分发**（Tauri 安装包）：维持封印。放行前置 = §5-6 路径裁决
  + §5-3/5-4 依赖机械普查。§5-2 摇树实测已闭合（红线全过，见 §5-2）。

## 4. 与冻结规则的对齐检查

- 凭据/Cookie/上游原始响应不进 Event/日志（THIRD_PARTY_NOTICES 末段
  承诺；切片 1 的 provenance/context 契约与 cookieMirror 隔离实现一致）。
- LearnX 例外触发条件（清华信息化技术中心任职/清华关联资助）：**无
  learnX 代码拷贝 → 拷贝面不触发**；项目资助状态属协调人层面事实，
  列入澄清问题（§5-5）。
- OneTHU 附加限制①的"资助"子句同样依赖项目资助事实（§5-5 同问）。

## 5. 未澄清清单（§5-1/§5-2 已实测闭合；其余为发布硬门）

1. **[已闭合，结论不利] info-lib 基线归属**：上游两基线三方逐文件
   diff（thu-info-app @ `06dc3cf0` vs tag `v3.17.0`，工作副本
   blob:none + sparse 检出；行变化数 = `diff | grep -c '^[<>]'`）：
   `core.ts` ours-vs-3.17.0=**48** / ours-vs-06dc3cf0=242（48 行全为
   THIRD-PARTY.md 自述 OneTHU 适配：rtn-network-utils 剔除、finger3
   修复）；`error.ts` ours-vs-3.17.0=**0**（逐行相同）；`strings.ts`
   =**7**（vs 136）；`network.ts` 重写（336/475），残留重叠偏 3.17.0
   侧（51 vs 43）。**结论：四文件均 post-BSL（v3.17.0）派生**，BSL 1.1
   与授权点名问题同时激活（上游 v3.17.0 LICENSE：Grant **None**、
   Change Date 2030-09-15，首发 2026-09-15 双源坐实——与 §1 的邮件日期
   2026-09-16 非同一事实）。**裁决路径二选一**（协调人/用户决定）：
   **A** = 向 THU Info 团队确认 2026-09-16 邮件授权延伸至 Agenthu
   分发链（书面答复存档）+ 改正 info-lib/LICENSE 基线声明为 3.17.0；
   **B** = 四文件回退从 `06dc3cf0` MIT 快照重推导（desktop 引用面
   **4/6 在 MIT 基座**——login/roam/getCsrfToken/uFetch；
   clearOutstandingLogin/setPlatformFetch 随适配层平移，两符号零上游
   谱系、OneTHU 自有，与 vendored LICENSE 自述咬合——实测无功能损失；
   OneTHU 适配层 48/7/0 行可平移），
   使现 LICENSE 声明成真。
2. **[已闭合，红线全过] bundle 内含物实测**（`pnpm -C apps/desktop
   build`，vite 单 chunk `index-*.js` 1005.76 kB / gzip 329.15 kB）：
   - **venue：0 命中**（符号与 `sports.tsinghua.edu.cn` host 串双探针）
     ——附加限制②场馆自动预约能力二进制面零存在 ✓；
   - **coursex：0 命中** ✓；
   - **zhjwxk：5 处上下文命中**，归属 `core/src/info/client.ts:47`
     →`fetchZhjwxkPage` 传递引用（夏季学期一级课表只读兜底，GET
     `kbSearch`）；提交/退课/志愿类函数（submitXkCourse 等 6 符号）与
     `xkAction` 路径 0 命中——**无害解释成立，无需收窄**；§2.1 引用
     结论已修正（直接 import 0 ≠ 传递引用 0）；
   - learn/auth/info 等被引用模块在场 = 预期行为。
3. **npm 依赖全量普查**（desktop + contracts 的 package.json 树）：
   `pnpm dlx license-checker` 出 JSON 归档；非许可（GPL 族等）若出现
   即升级为阻断项。
4. **cargo crate 普查**：`cargo deny check licenses`（或 cargo about）；
   现有直接依赖人工初筛全部宽松（tauri/reqwest/tokio/rusqlite/
   stronghold/keyring 等 MIT/Apache 系；rusqlite bundled SQLite 走
   Notice 条款）。
5. **项目资助事实确认**（协调人层面）：Agenthu 是否接受/计划接受任何
   清华关联机构资助——同时决定 OneTHU 附加限制①子句与 LearnX 例外
   条款的风险评估输入。
6. **授权邮件延伸**（§5-1 后升级为**发布总门**）：THU Info 授权点名
   OneTHU；实测已证 post-BSL 派生文件存在 → 路径 A 的书面确认或
   路径 B 的回退重推导，二者必居其一才能解除源码+二进制分发封印。

## 6. 下一步（正式 P0-6 切片内）

§5-1/§5-2 两实测动作**已执行并回填**（本提交）。剩余序列：
**协调人/用户对 §5-1 裁决路径 A/B 拍板** → 按路径改正
info-lib/LICENSE（A）或执行回退重推导（B）→ §5-3/5-4 依赖机械普查 →
更新根 THIRD_PARTY_NOTICES.md（吸收逐文件表与分发结论）→ PR 走
head-bound 互审。清点阶段总结论修订：**源码面与二进制面在 §5-6
裁决前双双封印；venue 红线与摇树面已实测过关。**
