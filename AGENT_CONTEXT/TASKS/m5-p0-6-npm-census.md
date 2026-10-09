# M5 P0-6 §5-3：npm 依赖树许可普查（B）

- 状态：已完成实测（结果落 m5-p0-6-license-inventory.md §8，2026-10-09；cargo 普查先并占 §7）；RC 修正轮 2026-10-09（见 §2）
- 负责人：B（juefan-web）
- 分支：`docs/m5-p0-6-npm-census`（基 main `bf8f243`）
- 依据：P0-6 发布门序列（m5-p0-6-license-inventory.md §6：路径 B 合并后 → §5-3/§5-4 依赖机械普查 → §5-5 资助事实）；方法沿用 #79 三面逐文件谱系法；产出直接进 `m5-p0-6-license-inventory.md` 新节
- 与 §5-4（A 的 cargo census）相互独立、可并行

## §0 执行框（实现前冻结）

### 目标与输入

对**源码分发将携带的 npm 依赖树**做逐包许可普查：

- **权威清单** = `pnpm-lock.yaml` `packages:` 段（分发携带物本体，239 个 name@spec 锁定项——冻结时实测数）；五个 workspace importer（root / apps/desktop / packages/contracts / vendor/onethu/core / vendor/onethu/info-lib）的直依赖面逐一列出。
- **许可事实** = 已装 store（`node_modules/.pnpm`，冻结时 184 项）各包 `package.json` 的 license/licenseText 字段；store 缺项（平台特定/未装）标记来源为 lockfile-only 并列为未解析面。
- **交叉工具** = `pnpm dlx license-checker`（inventory §6 点名方法）对 apps/desktop 面跑一遍做数字对账；网络不可用则记录并声明单方法依据。

### 方法（三面谱系，沿 #79 纪律）

1. **谱系面**：lockfile 全量 → 逐包 license 取值 → 分级归类。
2. **传递闭包面**：vendored 依赖（`vendor/onethu/core`、`vendor/onethu/info-lib` 的直依赖及其 lockfile 传递闭包）单独成表——BSL 谱系问题在路径 B 已关闭，此面证明 vendored 树内无新增非宽松项。
3. **事实面抽查**：直依赖（五个 importer 的 dependencies）做 license 字段 vs 包内 LICENSE 文件一致性抽查；传递依赖以字段为准（普查不升级为法务审查）。

### 分级口径

- **宽松**：MIT / ISC / BSD-\* / Apache-\* / Zlib / Python / Unlicense / CC0 / CC-BY-\* / 0BSD / BlueOak / PostgreSQL。
- **Copyleft（红旗）**：GPL-\* / AGPL-\* / LGPL-\* / MPL-\* / EPL-\* / EUPL。
- **源可得商业（红旗）**：BUSL / BSL。
- **未解析（红旗）**：UNLICENSED / "NONE" / 无字段 / 多许可表达式无法机械归类。
- **其他**：以上未覆盖者逐个列出（如 (MIT OR GPL) 双许可按更严格侧计列）。

### 验收

- A：lockfile 239 项全量分类（或显式标记未解析并给原因），分级计数与逐项表进 inventory 新节；**零未标记的 copyleft/BSL/未解析红旗**（发现即列finding）。
- B：vendored 传递闭包表独立成节；五个 importer 直依赖清单 + 抽查结果。
- C：license-checker 交叉对账数字（或网络不可用记录）；单工具/双工具口径差异说明。
- D：本普查**不解除任何封印**（§5-4/§5-5 未闭前源码公开化与二进制双封印维持）；普查只产出事实与红旗，不改动任何依赖、不升级为法务结论。

### 边界与不负责

- 不负责 cargo 面（A 的 §5-4）；不做法务定性（红旗=需协调人/用户裁决的事实，不是结论）；不改动依赖或锁文件；bundle 内实际打包面已在 §5-2 摇树实测闭合（本普查是树级普查，与 §5-2 面互补）。

## §1 实测记录（2026-10-09）

全部数字见 `m5-p0-6-license-inventory.md` §8。要点：232/232 全量分级
**零红旗**；平台 optional 50 项经 npm registry 全 MIT；vendored 闭包 25
项全宽松；desktop 全闭包 209 项零非宽松；交叉工具 license-checker 受
pnpm 布局限制仅见 23 项、可见面一致。Findings：自有 5 包无 license
字段 + 根无 LICENSE（封印自洽、公开化前须定许可，属协调人/用户层）；
caniuse-lite CC-BY-4.0 署名链随 Notice 吸收。

过程账（透明）：普查脚本经四轮修正——CRLF 尾断正则、scoped 包双层
glob、snapshots 单行 `key: {}` 锚、registry 查询须走 bash（npm 是
.cmd）；每轮修正后全量重跑，最终 232/232 解析覆盖自洽（packages 与
snapshots 双段计数相等）。

## §2 RC 修正轮（2026-10-09；协调人 RC 打回后 B 重测 v5→v10）

RC 令五项修正；执行中用 yaml 全量解析 + 精确路径 license 读取 +
截断目录反查重测全账（v10 终版），**RC 的两项自身锚点无法复现**，
按实测事实呈报如下。

### 数字漂移链 239 → 232 → RC 227 → 实测 232（终）

- **239（§0 冻结数）——产生机制已复现**：packages 232 键 + snapshots
  多重 peer 后缀键经**单层剥离**残留的 7 个伪基键（`vitest@3.2.7(@types/node@26.6.3)`、
  `zustand@5.0.15(@types/react@19.3.0)`、`@vitejs/plugin-react@4.7.0(…)`、
  `@vitest/mocker@3.2.7(…)`、`@testing-library/react@16.3.3(…)`、
  `@csstools/css-calc@2.1.4(…)`、`@csstools/css-color-parser@3.1.0(…)`）
  的并集 = 232 + 7 = 239。冻结时计数命令未保存（过程缺陷，见下新规 4），
  推导机制现已完整可复现。§0 的「store 184 项」= `ls node_modules/.pnpm`
  原始计数（作为 ls 数为真，作为包计数错）。
- **232（v4 终报）——宇宙数正确，真错三处**：
  ① optional 明细写成 esbuild 24 + rollup 22；实测**未装侧** =
  esbuild 25 + rollup 23 + @napi-rs/lzma-linux-x64-gnu 1 + fsevents 1
  （家族**总**数 esbuild 26 + rollup 25 + 1 + 1 = 53；win32 本机实装 3：
  esbuild/win32-x64、rollup win32-x64-gnu + win32-x64-msvc——v4 漏计 gnu 那个）；
  ② vendored 闭包 25 → **27**、desktop 闭包 209 → **212**（v4 正则依赖
  解析漏了 entities@6.0.1/@7.0.1 两个版本键等 3 键）；
  ③ 5 个 pnpm Windows 长路径**截断目录名**未披露
  （`@babel+plugin-transform-rea_<hash>`、`@csstools+css-parser-algori_<hash>`、
  `@csstools+css-color-parser@_<hash>`、`@testing-library+react@16.3_<hash>`）——
  其身份须由目录内 package.json 反查，不能按目录名解析。
- **RC 227（协调人复测）——无法复现，提请复核**：yaml 全量解析
  `packages:` **232** = `snapshots:` 真基 **232**（peer 后缀全剥离后
  集合相等），`importers:` 5。一行复现：
  `python -c "import yaml;d=yaml.safe_load(open('pnpm-lock.yaml',encoding='utf-8'));print(len(d['packages']),len(d['snapshots']),len(d['importers']))"`
  → `232 232 5`。「3 个 playwright 目录过期不在 lock」亦不成立：
  `@playwright/test` / `playwright` / `playwright-core` **@1.63.0 即锁定版本**
  （lock packages 行 407/929/934、snapshots 行 1452/1954/1956），store
  三目录皆活。lock 三方一致（worktree = HEAD = origin/main = `4d74b9e`）。
  store 实测分解：`ls` **184** = 183 个目录（**182 版本目录** + 1 个
  `node_modules` 目录）+ `lock.yaml` 文件；**182 个版本目录身份全部在
  lock、零过期**。实测自洽模型：**232 = 182 已装 + 50 未装（全部为平台
  optional）**；「227 = 177 + 50」模型不成立。RC 分布表（MIT 190/ISC 13/
  BSD-2 10/Apache 9/MIT-0 2/BSD-3 1）同样无法逐键复现——本普查精确路径
  读取逐键可查（inventory §8 小桶清单），抽查实证：@csstools 家族仅
  color-helpers 为 MIT-0（css-calc/tokenizer/parser-algorithms/color-parser
  均 MIT，首匹配式读取会把 css-calc 误读成 color-helpers 的 MIT-0）；
  undici-types@8.9.0 实读 MIT。
  **本项待协调人复核；下表与分布以实测 232 为锚。**
- **分布表 199/11/9/8/2/1/1/1 在 v4→v10 重测中未变**（v4 的 license
  归属实际未错；错的是闭包与 optional 明细）。

### 新规（RC 裁定⑤ + 实测收紧，自本任务书起生效）

1. **普查分母永远取 lock**（yaml 全量解析；正则中间产物禁入报告）。
2. **store 只作 license 事实源**，须按精确路径
   `.pnpm/<dir>/node_modules/<name>/package.json` 读取；禁止对目录内
   package.json 做首匹配枚举（易把同目录邻包 license 误归属）。
3. 截断目录名（Windows 长路径）一律由目录内 package.json 反查身份。
4. 冻结时点数字必须与终测同脚本同保存命令产出。
