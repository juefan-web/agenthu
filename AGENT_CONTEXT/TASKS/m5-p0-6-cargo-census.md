# M5-P0-6 §5-4：cargo crate 依赖许可机械普查（A 执行片）

Status: **已执行完毕（A，2026-10-09）：§0 先落字 @`ed61408`（独立 commit），随后普查 579/579 全覆盖——permissive 573 / weak 5（全 MPL-2.0）/ strong 0 / special 0，红线零触发；产出已回填 license-inventory §7。零代码改动（docs-only）。待 B head-bound 互审。**

## 0. 边界（冻结）

**目标**：`apps/desktop/src-tauri` cargo 依赖树全量逐包许可归类 + 红线判定，产出回填 `AGENT_CONTEXT/TASKS/m5-p0-6-license-inventory.md` 新节（§5-4），作为分发封印放行的 §5-4 侧输入。

**方法（工具裁定：本地随树文件读取法，承重；cargo deny / cargo-license 不作承重、可作交叉复核）**——沿用 #79 §0 方法条款"条款以随树许可文件为权威"：

1. `cargo fetch --locked`（src-tauri）将本地注册表缓存补齐至 lock 全集（已实测可行）；普查对象 = 各 crate 发布物随树的许可材料，而非 crates.io API 元数据。
2. 逐包读缓存 crate 目录：随树 `Cargo.toml` 的 `license` / `license-file` 字段 + 随树 LICENSE*/COPYING* 文件在场核验；字段缺失、字段与文件不一致、非标准表述 → 如实标注，不静默归类。
3. 归类面：permissive（MIT / Apache-2.0 / ISC / BSD / Zlib / Unicode / CC0 / Public-domain / Notice 系）/ weak copyleft（MPL-2.0 等，文件级义务）/ strong copyleft（GPL / AGPL / LGPL 族）/ 特殊（BSL、non-standard、多重许可）。多重许可按可满足的最宽面归类并全文记录原始表述。
4. 特例如实记录（以实测为准，不预设）：rusqlite bundled SQLite（上游 Public Domain / Notice 义务）、可能的多重许可 crate、windows 目标系 crate 等。

**红线（承重）**：strong copyleft 出现 → 即时升级为阻断项并停工上报，不在本片内自行处置；非 permissive / weak 全部列入未澄清清单随产出上报。

**不负责**：npm 面（B §5-3 并行，方法独立）；§5-5 资助事实；解除分发封印（本普查仅为前置输入）；根 THIRD_PARTY_NOTICES.md 更新（§5-3/5-4/5-5 全闭后统一动作）；cargo deny CI 门禁化（未来另裁）。

**产出面**：license-inventory.md 新增 §5-4 节——方法、包总数与来源分布、归类分布、非 permissive/weak 逐包表、红线判定、对分发结论的输入；本任务书记录执行过程与实测数字。普查脚本不入仓（方法与命令在任务书内可复现）。

**验收**：①579 包全覆盖（逐包计数与 Cargo.lock 实测对账）；②每包归类有随树文件依据（字段或文件）；③红线判定明确（GPL 族 0 或阻断上报）；④回填 license-inventory 新节；⑤本片零代码改动（docs-only + 数据实测）。

## 1. 执行记录（A，2026-10-09）

**执行序**（§0 冻结先行）：

1. `cd apps/desktop/src-tauri && cargo fetch --locked` —— 缓存自 545 补齐
   （fetch 后 703 目录，lock 全集在内；Cargo.lock 零改动，`--locked` 不重解）。
2. 普查脚本（一次性，不入仓，逻辑：解析 Cargo.lock 全包行 → 定位
   `~/.cargo/registry/src/index.crates.io-*/{name}-{version}/` → 读随树
   Cargo.toml `license`/`license-file` + 枚举 LICENSE*/COPYING* → SPDX
   表达式分类器：OR 分支感知（任一全 permissive 分支即满足）、斜杠方言
   归一为 OR、`WITH` 例外剥除、AND 取最严）。
3. 两轮跑法：首轮宽分类器（暴露伪影 38"SPECIAL"+2"STRONG"）→ 精化
   （MIT-0/BSD-1-Clause/Boost-BSL-1.0 入 permissive 集、OR 分支感知）
   → 终局 573/5/0/0。伪影清单逐项人工核对（斜杠双许可 26 包全为
   MIT/Apache 族方言；r-efi 两包 LGPL 为三选一 OR 的非承重分支）。

**实测数字**（全部出自脚本输出与随树文件直读）：

- 579 包行 = 578 registry（`source = "registry+..."`）+ 1 自有（无
  source，`agenthu`）；非 registry 源 0。
- 归类：permissive **573** / weak **5**（cssparser、cssparser-macros、
  dtoa-short、option-ext、selectors，全 MPL-2.0）/ strong **0** /
  special **0**；自有 1。
- 随树许可文件在场 528/578；仅表达式无文件 50（含 r-efi ×2，README
  License 节与表达式同文、AUTHORS 在场）。
- 多版本并存 46 crate 名（windows-* 族为主），按包行计入 579。

**文件级实证（承重特例）**：ryu 随树 `LICENSE-BOOST` 开篇即 Boost
Software License 1.0 全文（SPDX BSL-1.0 = Boost，非 Business Source
License——本项目语境的关键区分，文件坐实）；libsqlite3-sys `sqlite3/`
内嵌 amalgamation（sqlite3.c/h），上游 SQLite 公共领域 → Notice 义务；
openssl 系锁文件面 0（reqwest 仅 rustls-tls）。

**产出**：license-inventory §5 条目 4 转"已闭合无阻断" + 新增 §7
（方法/分布表/特例/分发输入）；Status 行同步。零代码改动——CI 面无新
信号（docs-only 分支，tauri-rust/frontend 等检查照跑不涉本片）。

**未入本片**（按 §0"不负责"）：THIRD_PARTY_NOTICES.md 吸收（§5-3/5-4/5-5
全闭后统一）；cargo deny CI 门禁化（未来另裁）；封印解除（协调人层面）。
