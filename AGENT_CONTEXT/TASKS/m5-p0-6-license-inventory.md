# M5-P0-6 许可逐文件盘点（提前启动的清点阶段）

Status: **清点阶段完成（2026-10-07，#75 合并后并行启动——协调人既有授权
"许可盘点可在 #75 合并后启动，与代码线无耦合"）；正式 P0-6 切片待派工，
本文档即其输入。阻断规则：未澄清 → 不发布二进制。**

依据：THIRD_PARTY_NOTICES.md（项目级骨架，已存在）、
vendor/onethu/{LICENSE,VENDORED_FROM.md,LICENSES/THIRD-PARTY.md,
info-lib/LICENSE} 全文（本轮全部重读）、vendored 树与 apps/desktop 的
grep/结构普查（数字为实测）。上游 pin：
OneTHU `2e3455fc235719b7f91fffaf5fe35e09220dda73`。

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
| `src/caldav`/`src/exthw`/`src/privacy`/`src/zhjwxk` | 各模块 | OneTHU MIT+附加限制 | 否 | 同上 |
| `src/venue`（场馆） | client/sign/types.ts | OneTHU MIT+附加限制；**附加限制②点名"场馆自动预约提交"为禁用用途** | **否**（desktop 无 import 实测） | 源码树随仓分发无碍；**二进制与 UI 不得暴露自动预约提交能力**——现状一致（未引用），摇树验证 §5-2；产品红线：切片 2+ 的数据控制页等任何 UI 不接入 venue 提交面 |
| `test/*.smoke.mjs` 等其余 | 测试/配置 | OneTHU MIT+附加限制 | 否 | 源码树分发 |
| npm 依赖 | `aes-js`、`sm-crypto`（core package.json 实测仅此两项） | 各自 MIT（随包保留声明） | 经 auth/加密路径入 bundle | 二进制分发保留其许可声明；全量机械普查 → §5-3 |

### 2.2 `vendor/onethu/info-lib`（8 文件，6 .ts；auth-only 瘦身版）

| 文件 | 出处/许可 | 备注 |
| --- | --- | --- |
| `LICENSE` | 自带边界声明：基线 = 上游 `06dc3cf0`（**MIT 末代快照**，BSL 切换前），声明"post-BSL commits NOT incorporated by copy"，其上新增为 OneTHU 自有 MIT | **与上游 THIRD-PARTY.md 的"Vendored 基线 3.17.0"存在口径张力** → §5-1 |
| `src/lib/core.ts`（472 行，InfoHelper） | 上游 thu-info-lib 派生 + `OneTHU 适配` 标注（platformFetch 注入等适配层） | MIT 期代码 + OneTHU 适配；desktop import（login/roam/getCsrfToken）实测 |
| `src/utils/network.ts`（136 行） | 同上（`OneTHU 适配` 标注文件之一，上游 THIRD-PARTY 明列） | setPlatformFetch/uFetch import 实测 |
| `src/utils/error.ts`、`src/constants/strings.ts` | 上游 MIT 期常量/错误码 | — |
| `src/index.ts`（16 行） | **Agenthu 自写**（文件头首行 "Agenthu: auth-only interface" 实测） | auth-only 接口收窄声明 |
| `src/vendor.d.ts` | Agenthu 自写（sm-crypto 极小类型声明，仅 sm2.doEncrypt） | — |
| `package.json` | 元数据 | workspace: `@onethu/info-lib` |

**该 624 行瘦身树 ≠ 上游整库**；逐文件对上游两基线（`06dc3cf0` MIT 期 /
3.17.0 BSL 期）的 diff 归属 = §5-1 未澄清项主体。

### 2.3 `apps/desktop` 派生码面

- `src/adapters/campus/*`（onethuAdapter/tauriTransport/tauriAuthGateway/
  cookieMirror/events/index/runtime）：**消费型适配层**——import 面为
  类型 + 会话 + 数据读取函数（实测清单见 §2.1 引用列），未发现从
  OneTHU/learnX 复制的代码体；无 learnx 字样（grep 实测）。
- `src-tauri/src`（Rust 传输/Stronghold/SQLite）：onethu 字样仅为
  cookie/会话桥接注释，无上游代码拷贝（grep 实测）。
- 结论：**Agenthu 自有代码 + 以依赖方式使用 vendored 包**；二进制为
  vendored 代码与 Agenthu 代码的合并作品，分发结论见 §3。

## 3. 分发结论（当前证据下的结论，§5 未澄清项闭合前**不构成放行**）

- **源码分发**（仓库/源码包）：随树保留 `vendor/onethu/LICENSE`（含附加
  限制全文）、`LICENSES/THIRD-PARTY.md`、授权邮件 eml、根
  `THIRD_PARTY_NOTICES.md`；接受方受 OneTHU 附加限制约束。条件现状：
  Agenthu 非商业个人工具 ✓；无攻击性访问用途面 ✓（venue 未接入）。
- **二进制分发**（Tauri 安装包）：bundle 内含 @onethu/core + info-lib
  编译产物（MIT 许可 + 附加限制随 NOTICE 保留）+ aes-js/sm-crypto +
  Rust crate 链。**放行前置**：§5-1 基线归属闭合（决定 BSL 1.1/授权邮件
  是否适用）+ §5-2 bundle 内含物实测 + §5-3/5-4 依赖机械普查。
  **未澄清 → 不发布二进制。**

## 4. 与冻结规则的对齐检查

- 凭据/Cookie/上游原始响应不进 Event/日志（THIRD_PARTY_NOTICES 末段
  承诺；切片 1 的 provenance/context 契约与 cookieMirror 隔离实现一致）。
- LearnX 例外触发条件（清华信息化技术中心任职/清华关联资助）：**无
  learnX 代码拷贝 → 拷贝面不触发**；项目资助状态属协调人层面事实，
  列入澄清问题（§5-5）。
- OneTHU 附加限制①的"资助"子句同样依赖项目资助事实（§5-5 同问）。

## 5. 未澄清清单（发布硬门；每项附闭合动作）

1. **info-lib 基线口径张力**（最高优先）：随树 LICENSE 称基线
   `06dc3cf0`（MIT 期、post-BSL 不拷贝）vs 上游 THIRD-PARTY.md 称
   "Vendored 基线 3.17.0"（BSL 期 + 授权邮件）。若任一文件含 post-BSL
   派生逻辑 → BSL 1.1 与"授权点名 OneTHU"两个问题同时激活。
   **动作**：对上游两 tag 逐文件 diff（`git diff 06dc3cf0 3.17.0 --
   <files>` 于 thu-info-app 检出），把 6 个 .ts 归到 MIT 期/OneTHU 自有/
   post-BSL 三类；结论回填 §2.2。
2. **bundle 内含物实测**：desktop 经 `main: src/index.ts` barrel 引用
   core，无 `sideEffects` 声明——learn/venue/coursex 等未引用模块是否
   被摇树剔除未经证实。**动作**：`pnpm -C apps/desktop build` 后
   `grep -l "venue\|coursex\|zhjwxk" dist/ -r`；若在场且无无害解释 →
   需显式子路径 import 收窄引用面。
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
6. **授权邮件延伸**：THU Info 授权点名 OneTHU；若 §5-1 判定存在
   post-BSL 派生文件，需向 THU Info 团队确认授权是否延伸至 Agenthu
   的分发（或该等文件改从 MIT 期快照重实现）。

## 6. 下一步（正式 P0-6 切片内）

执行 §5-1/5-2 的两个实测动作 → 回填 §2 → 更新根 THIRD_PARTY_NOTICES.md
（吸收逐文件表与分发结论）→ PR 走 head-bound 互审。本清点阶段结论：
**源码面条款链完整可守；二进制面在 §5-1/5-2/5-3/5-4 闭合前保持封印。**
