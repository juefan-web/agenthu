# M5 P0-6 路径 B：vendored info-lib 四文件从 MIT 基座重推导

- 状态：已完成实现与本地验收，待 PR 互审
- 负责人：B（juefan-web）
- 分支：`feature/m5-p0-6-info-lib-rederive`（基 main `75167c8`，即 #79 落点）
- 依据：#79 普查结论（四文件 v3.17.0 post-BSL 谱系）+ 协调人路径 B 裁定（自足性 / 实测零功能损失 / LICENSE 假话必须成真 / AGENTS.md 姿态）+ 新规矩（执行框落 §0 后动手）
- 上游仓：https://github.com/thu-info-community/thu-info-app （packages/thu-info-lib）
- 基座：`06dc3cf0`（2024-07-10 14:53 +0800，MIT 最后快照；同日 15:07 +0800 `33fd0a86` 切 BSL 1.1）

## §0 执行框（实现前冻结）

### 目标形态

| 文件 | 目标 | 依据 |
|---|---|---|
| `utils/error.ts` | 06 基座原样（弃 ours 多出的 `UseregAuthError`——post-BSL 新增，仓库零消费者） | 0 行适配层 |
| `constants/strings.ts` | 06 基座原样 + SECONDARY_URL 直连改（OneTHU，7 行含注释） | 7 行适配层 |
| `lib/core.ts` | 06 基座 + 平移 OneTHU 48 行增量 + 活面协议独立重推导（四项精确化见下） | 48 行适配层 + 独立实现 |
| `utils/network.ts` | 维持 OneTHU 整写（platformFetch 注入、无自管 cookie、UTF-8 only）；头部注释的谱系自述随 LICENSE 一并改真 | OneTHU 自有重写 |
| `index.ts` / `vendor.d.ts` / `package.json` | 原样不动 | 契约面冻结 |
| `LICENSE` | 改写为真话：06 基座 + OneTHU 适配/整写 + 边界后协议独立实现 + auth-only 收窄 | 本片核心目的 |

### 四项精确化

1. **hunk 二分法**。实测 ours-vs-p317 差分：core 48 行、strings 7 行、error 0、network 整写。core/strings 的该增量 = OneTHU 自有工作，整体平移到 06 基座上；其余 p06→ours 差分按「活面/死面」二分处理：
   - **活面**（桌面实际行使语义，按 ours 语义独立重推导，保零契约漂移）：`login(helper, userId, password)` 三参、登录链内 `roam(helper, "id", "10000ea…")`、`getCsrfToken`、`clearOutstandingLogin`、2FA hook 面（`twoFactorMethodHook(wechat, phone, totp)` 三参、`twoFactorAuthLimitHook`、`trustFingerprintNameHook`）、SM2 密码加密、OAuth 落地取钥、`fingerGenPrint` 信任链、roam "id" 直连表单 + `getWebVPNUrl` 包装跟随。
   - **死面**（桌面零调用，回 06 基座原样剥谱系）：roam `default`（dzpj 用户名/密码版）与 `gitlab` 分支语义、`forgetDevice` 与设备管理三 URL、`id_website`/`madmodel`/`zzjl`/`zhjwxk` 扩展漫游、`getRedirectLocation` OpenHarmony 钩子。
2. **finger3 裁定修正**（更正预核倾向「丢弃 finger3、桌面测试改 finger3=''」）：实测推翻——finger3 捕获块（`helper.fingerGenPrint = String(parsed.object ?? "")`）在 ours-vs-p317 的 48 行 OneTHU 增量内，且为桌面信任链活代码（`tauriAuthGateway.ts:216-217` 保存、`:101/:170/:195` 复灌、测试 `:194-205` 背书）。→ **保留**捕获块与 `fingerGenPrint: helper.fingerGenPrint ?? ""`（roam id 族两位点）；丢弃面仅为上游 checkSingle/设备管理流。桌面测试与网关代码零改动。
3. **SM2 / OAuth / totp 按学校协议独立重推导**。今日服务端硬门：裸密码被拒、落地页 `#sm2publicKey`、doubleAuth 返回 `hasTotp` 且 totp 走 `VERITY_TOTP_CODE`。以 `sm-crypto`（package.json 已声明 + vendor.d.ts 已声明模块类型）重实现 `i_pass = "04" + sm2.doEncrypt(password, publicKey)`。选择器名、action 字符串、`04` 前缀为**服务端协议事实**，相似性不可避免；控制流、命名、注释按本仓风格重写，不搬上游表达。登录链保留双跳 `WEB_VPN_OAUTH_LOGIN_URL`（请求序零漂移）。`getRedirectLocation` 在本包不可赋值（模块私有 `let`、无 setter 导出、仅有的两个使用分支属上游谱系死码）→ 整体剔除；桌面传输自跟随重定向、`getRedirectUrl` 回 finalUrl，行为等价。
4. **死面回 06 + 工具链机械转换**。HOST_MAP 取 06 的 14 项原样；roam `default`/`gitlab` 分支取 06 语义（对今日服务端形态未验证，标注非承载面）；`cr` 分支依赖未 vendor 的 `./cr` → 连同 `RoamingPolicy` 的 `"cr"` 成员一并剔除（auth-only 收窄，与 index.ts 自述一致）。cheerio@1.2.0 ESM 无默认调用形态 → star import + `cheerio.load()` 机械转换（roam/login 共 3 处调用点）。

### 验收（回差证据，实现后逐项落 §1）

- **A1** 新文件-vs-p06：差分 = 纯适配层（OneTHU 增量 + 独立重推导活面 + 工具链转换），显著小于旧 ours-vs-p06 的 242 行差分面。
- **A2** 新文件-vs-p317：差分显著大于旧 ours-vs-p317 的 48 行——post-BSL 谱系面被剥离。
- **B** grep 面：`CHECK_CURRENT_DEVICE|GET_DEVICE_LIST|DELETE_DEVICE|forgetDevice|id_website|madmodel|getRedirectLocation|require(|UseregAuthError` 在 vendor/onethu/info-lib 内零残留。
- **C** 契约零漂移：index.ts / vendor.d.ts / package.json / tauriAuthGateway.ts / tauriAuthGateway.test.ts 零改动；desktop `tsc` + `vitest` 实测绿。
- **D** LICENSE 声明可被本任务测量复证（06 基座事实、OneTHU 增量事实、独立实现清单、auth-only 收窄）。

### 风险登记

- 学校若把设备指纹流改为硬门（checkSingle 强制），MIT 基座缺该流需重估——丢弃面清单在案可回补。
- SM2 相似性边界：协议事实不构成表达复制；若上游主张更大范围，属法务层判断，超出本切片权限，上报协调人。
- 死面分支保留 06 语义 = 对今日服务端未验证；未来任何启用须先按活面流程重走。
- **分发封印不因本片解除**：§5-3 npm census / §5-4 cargo census / §5-5 funding 事实仍待，见 m5-p0-6-license-inventory.md §6 顺序。

## §1 实现记录与回差实测（2026-10-08）

### 交付面（git status 实测，恰好 5 文件）

`vendor/onethu/info-lib/{LICENSE, src/lib/core.ts, src/utils/network.ts, src/utils/error.ts, src/constants/strings.ts}`；index.ts / vendor.d.ts / package.json / apps/desktop 全部零改动（+179/−231）。

### 逐文件落法

- **error.ts** = 06 基座逐字节（弃 `UseregAuthError`）。
- **strings.ts** = 06 基座 + SECONDARY_URL 直连 hunk（7 行含注释，OneTHU）。
- **core.ts** = 06 结构 + 适配层：活面（login / twoFactorAuth / roam-"id"）按 ours 语义独立重推导（SM2、OAuth 落地双跳、totp 三参、finger3 捕获、`fingerGenPrint ?? ""`、getWebVPNUrl、timer/clearTimeout、clearOutstandingLogin）；死面（roam default/card/cab/gitlab、HOST_MAP 14 项、verifyAndReLogin/roamingWrapper 族）回 06 原样（cheerio@1.2.0 机械转换 3 处调用点 + `import type`）；剔除 cr 分支与 RoamingPolicy 的 "cr" 成员、getRedirectLocation、forgetDevice。
- **network.ts** = 正文与旧版逐字节一致（OneTHU 整写面不动），仅头部谱系自述随 LICENSE 改真（+1 行差分）。
- **LICENSE** = 三段式真话：① 06dc3cf0 基座事实（含 BSL 切换点与 Change Date）；② 本仓自有工作清单（network 重写 + core 认证适配 + auth-only 收窄）；③ 边界声明（post-BSL 不抄录；边界后协议能力按可观察协议独立实现；残余相似限于协议事实）。

### 验收实测

| 项 | 旧值（#79 普查） | 新值（本片实测） | 判定 |
|---|---|---|---|
| A1 core-vs-p06 差分行 | 242 | **145** | 纯适配层 ✓ |
| A1 strings-vs-p06 | 136 | **7** | ✓ |
| A1 error-vs-p06 | 4 | **0** | ✓ |
| A1 network-vs-p06 | 336 | 337（正文不变，头部 +1） | 持平，谱系靠声明 ✓ |
| A2 core-vs-p317 | 48 | **233**（4.9×） | 谱系剥离 ✓ |
| A2 strings-vs-p317 | 7 | **136**（19×） | ✓ |
| A2 error-vs-p317 | 0 | **4** | ✓ |
| B 残留 grep（12 模式） | — | 全零（CR_LOGIN_HOME_URL 命中为 06 基座常量定义、零使用） | ✓ |
| B finger 形状 | — | core 12 hits = p06 12 hits；strings 1 = 1 | ✓ |
| C 契约零漂移 | — | 5 文件；index/vendor.d.ts/package.json/网关/测试零改动 | ✓ |
| C typecheck | — | `pnpm typecheck` 三包绿 | ✓ |
| C vitest | — | 33 文件 / 244 测试全绿（含 tauriAuthGateway 11） | ✓ |
| C build | — | bundle 1005.79 kB / gzip 328.96 kB（基线 1005.76/329.15） | ✓ |
| D 红线复测 | venue 0 / coursex 0 / zhjwxk 5 / xkAction 0 | **全部 0**（zhjwxk 5→0：HOST_MAP 死键剥离） | 变好 ✓ |

### 留痕

- zhjwxk HOST_MAP 键丢弃的边界确认：桌面 roam 仅 "id"；@onethu/core 的 fetchZhjwxkPage 用自有 URL，不经 info-lib 模块私有 HOST_MAP。
- 死面（roam default/gitlab/card/cab）保留 06 明文语义 = 对今日服务端未验证；启用前须按活面流程重走（风险登记在案）。
