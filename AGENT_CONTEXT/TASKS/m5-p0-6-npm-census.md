# M5 P0-6 §5-3：npm 依赖树许可普查（B）

- 状态：进行中（§0 已冻结，实测中）
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
