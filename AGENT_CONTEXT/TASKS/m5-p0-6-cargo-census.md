# M5-P0-6 §5-4：cargo crate 依赖许可机械普查（A 执行片）

Status: **§0 先落字（A 拟，2026-10-09，协调人派工 §5-4、工具形态 A 自裁；B 复审把关）。普查面实测：Cargo.lock 579 包 = 578 registry + 1 自有 crate `agenthu`，零 git/path 源。**

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
