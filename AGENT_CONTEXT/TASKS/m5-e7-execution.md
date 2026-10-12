# M5-E7 执行轮任务书：双轮执行与收口材料（P0-7）

Status: **派工落字（2026-10-09，协调人；同日深夜修订）。P0-5/P0-6 门槛
仍满足，但外部审查（f360c21）回应轮 R1–R3 + NOTICES 对账吸收**先行**
（见 external-review-f360c21-response.md §5：#5/#6/#7/#9/#13 恰在本验收
断言面上）——**双轮顺延至该轮全合后的 main HEAD 执行**。通道裁定=形态 2
（§1）；r1=A、r2=B 同 head 双轮（§2）；E7-10 三分项拆分（§3）不变。
双轮未全绿且交叉复核未落前，M5 不收口。**

依据：D-030 M5 出口判据；[m5-e7-acceptance](m5-e7-acceptance.md)（r1
冻结稿，用例硬断言以该稿 §2 为准）；[m5-e7-fixtures](m5-e7-fixtures.md)
§9（执行轮前置项，本任务书为其落定）；`tests/e7/README.md`（runbook）；
license-inventory §9 用户裁定①②③④。

## 0. 边界（冻结）

**目标**：E7-1～E7-10 在同一执行 head 上双轮执行全绿（E7-10 按 §3
拆分），产出双轮脱敏证据汇总与逐案核账，作为 M5 收口判定材料。

**输入**：main 执行 head（§2 冻结规则）；`tests/e7/` 全套（seed/seed_spec/
manifest/verify/cases，提交在库）；`docker-compose.multi.yml`（E7-9 承载，
P0-5 切片 3 合入面）；e6-replay.mjs（provider 假件，:9099）；
license-inventory §7/§8/§9 终态（E7-10 许可分项对账输入）。

**输出**：双轮证据目录 `output/e7/r1|r2/`（本地受控，gitignored）；
脱敏汇总与形态数字回填本任务书 §6；逐案 verify 报告 JSON 摘录（族计数、
marker 扫描、对象/Redis 面）；执行 SHA / 树状态 / 构建指纹；不符预期
对账清单（含原始失败与恢复账）。

**负责范围**：仅执行与核账。任一轮发现产品或 harness 缺陷 → 停轮、开
修复 PR、合并后双轮在新 head 重跑（旧轮证据保留为过程账，不凑数）。

**不负责**：M5 收口登记（协调人，E7 双轮后另轮）；真实 key 轮换操作
（有权限操作者/用户层，本任务书只登记证据位状态）；发布封印变更（用户
裁定②维持，任何 E7 结果不解除）；THIRD_PARTY_NOTICES 吸收（A 的文档
任务，license-inventory §7/§8 为输入，不与 E7 轮混批）。

**验收标准**：

- baseline（未操作世界）双轮全绿；
- E7-1..E7-9 全案绿 + E7-10 机制面绿（§3 拆分）；
- expected 与 manifest 零跑后修改（op-4 计数注册随驱动落，§2）；
- B 独立核账无未解释残差；双轮交叉复核记录在案；
- 脱敏纪律零违例（§5）。

## 1. 审计通道裁定（fixtures §9 前置项落定）

**裁定：形态 2**——B 机自建 E7 栈自跑，证据各自独立产生；A 只交
seed/verify 代码与 runbook（已在 main，tests/e7/）。

理由：① 双轮协议本要求同 head 两轮各自新 seed，r1=A 机 / r2=B 机一次
满足「双轮」与「独立产生证据」两个要求；② B 机 dev 栈在运行
（agenthu-db-1 / agenthu-s3mock-1），runbook §1–§3 为逐条命令，自建
成本受控；③ 第二台机器的独立复现顺带验证 runbook 可移植性（M5
「部署形态」维度的免费证据）；④ 本仓两起计数事故（B v4 污染、协调人
锚定事故）的共同教训是独立复现优于转述数字。

**重裁（2026-10-11 晚，协调人）**：理由② 前提失效——B 机实测与协调人
本机只读复核双源坐实：docker/podman/Docker Desktop 零存在、
5432/9090/6379/6380/8011/9099 六端口零监听、本地无 psql、WSL Ubuntu
（WSL2）为净系统。按冻结升级路径回落**形态 1**（任务书预设降级，E6
先例）：r1 = A 机全量执行产结构化证据包并保留栈；B 做**库面抽查**
（A 栈保留期间）+ 对 r1 证据包的 manifest/runbook 口径机械互审——
「无 B 核账」不发生。**形态 2 经 WSL 原生建栈（apt 安装
postgresql-16+pgvector/redis/nodejs 等，约 1GB+）列为用户授权后的
可选补充轮**：属用户资产系统级安装，非 M5 出口门所需；授权后作为
过程账独立轮补强（不同 OS 基底的独立性反而更强）。

轮次分派：**r1 = A**（A 机，harness 作者首轮，环境问题暴露成本最低）；
**r2 = B**（B 机独立自建栈 + 新 seed）。B 机自建可与 A 轮并行提前
（栈立起后 `--baseline` 自验，不触用例）。

**升级路径**：B 机栈立不起（端口/镜像/资源冲突）→ 如实报阻断 → 回
协调人重裁；候选降级形态 = 形态 1（A 产结构化证据包 + A 栈保留供 B
库面抽查，E6 先例）。**任何情况下不得自行降级为「无 B 核账」。**

## 2. 执行 head 与双轮纪律

- 执行 head = A 轮开跑时的 main HEAD（A 报告落 SHA、树状态、构建
  指纹）；B 轮必须在**同一 SHA** 执行（临时 worktree/克隆锚定，不追新）。
- 每轮从新 seed 开始（`AGENTHU_E7_ROUND=r1|r2` 区分证据目录）；
  两轮协议其余照 acceptance §4（同 spec/构建/执行 head）。
- **op-4 驱动标注与计数注册随驱动运行落**（E7-1 的 op-4 执行轮补标注，
  #76 修复轮挂项）：manifest 预登记不得跑后修改凑绿——常设纪律，
  与通道裁定无关。
- 夜窗守卫与硬门交互按 acceptance §4：守卫跳过不得充证，涉删除硬门
  必须另有固定锚点的有效通过证据；建议白天窗执行。

## 3. E7-10 红门拆分与衔接顺序

E7-10 拆三个分项，分别处置：

1. **机制面（replay 可证）**：旧 key 拒绝/新 key 可用（假件轮换语义）、
   restore 先重放抑制再放流量、隔离恢复无已删内容/旧队列复活、RPO/RTO
   实测——走双轮硬断言。
2. **许可门**：对账输入 = license-inventory 终态（§7 cargo / §8 npm
   双普查零红旗 + §9 裁定②③）。执行只引用对账，**不重新普查**；
   当前状态 = 源码面事实公开、分发封印维持（README `a70f7e2`）。
3. **真实 key 轮换证据位**：操作者级（用户层动作）。双轮如实登记
   「未提供」，不得以 replay 充数（acceptance §2 尾注）。**发布门与
   M5 出口门分离**（D-036 §8-7）：该证据位空缺不阻断 E7 双轮判定与
   M5 收口，但分发封印维持至终局点（裁定②④口径）。

**衔接顺序**：① B 机自建栈（可与 A 轮并行）→ ② r1=A：baseline →
E7-10 红门单独先跑（早暴露阻断，红则按分项拆报并记录阻断项，其余用例
照跑）→ 全案 E7-1..E7-9 → ③ r2=B 同 head 同序 → ④ 交叉复核（A 核
B 轮证据包、B 核 A 轮证据包，机械对照 manifest 与 runbook 口径）→
⑤ 回填本任务书 §6 → 转协调人 M5 收口（含许可/恢复/key 门证据状态
如实转录）。

## 4. 用例执行面

- E7-1～E7-10 硬断言以 acceptance §2 冻结表为准（含 E7-3 锚定判据、
  E7-7 逐条预登记 ①–⑤）；驱动与预期以 `tests/e7/manifest.json`
  （提交在库，普通 CI 钉漂移）为准。
- E7-9 用 `docker-compose.multi.yml`（2 API + 2 worker + 真实 Redis +
  Collector）；provider 假件接 e6-replay.mjs（`OPENAI_BASE_URL=:9099/v1`）。
- AUDIT_ENABLED=false 栈口径照 runbook §2；seed 行仍证 §5 脱敏面。

## 5. 证据与脱敏纪律（E6 纪律沿用）

- `output/e7/` 本地受控留存，脱敏汇总入本任务书 §6；不推公开仓。
- 真实个人内容、真实 key 值永不进 fixtures/日志/证据/报告（只记 key id
  与结果）；marker（E7MARK-*）不得出现在日志/trace/errors/审计——E7-9
  断言 + P0-5 allowlist 出口双保险。
- 报告不虚构中继原文；A 留原始失败与恢复账，不修数、不筛行；每个不符
  预期显式对账；B 仅声称自己可证范围。

## 6. 执行回填（双轮后填）

（轮次 / 执行 SHA / 形态数字 / 不符预期对账 / 残差清单 / B 核账结论 /
交叉复核记录 / E7-10 三分项状态——待填）

## 7. 决议记录

- 2026-10-09 协调人派工：审计通道=形态 2（r1=A 机、r2=B 机）；E7-10
  三分项拆分如 §3（发布门与出口门分离）；op-4 注册纪律重申；M5 收口
  归档（含过程台账两案与新锚定硬规）由协调人在 E7 双轮后执行。
- 2026-10-11 协调人重裁（B 阻断报告触发）：E7 审计通道回落形态 1
  （B 机无容器/数据库基础设施，双源坐实）；B 核账角色经库面抽查 +
  机械互审保全；WSL 形态 2 为用户授权后的可选补充轮，不阻 M5。执行
  head 不变（8ee40d9），夜窗纪律不变。
- **2026-10-11/12 夜间裁定（2 案）——已作废**：r1 过程账后曾裁定
  驱动批 = E7-2 + E7-9/10 机制面两案。作废原因：A 全史核验坐实
  `tests/e7/cases/` 仅存在过一个内容提交（9925906：4 驱动 + 2 stub），
  E7-2/4a/4b/5/6/7/8 七动作案驱动**从未存在**（非丢失、非损坏），
  裁定前提（「七案驱动已在、只缺 2 案」）不成立。r1 门控 4p+2s 中
  4p 全部来自 E7-1/E7-3 参考驱动。留档为教训：派工前驱动存在性
  须以 git 历史锚定，不得以任务书条目推定。
- **2026-10-12 重裁（9 案驱动批，现行有效）**：范围 = 9 案
  （七动作案 E7-2/4a/4b/5/6/7/8 + E7-9 + E7-10）；昨夜 2 案裁定作废。
  作者归 A 独担（形态 1 下 B 机无栈，盲写驱动无法自证；驱动必须由
  能执行者写）；B 全批交叉审（静态精读 + 对照 A 的运行日志与
  manifest 计数）。批次结构（3 件 PR 串行合并）：D1 = ①+② 七动作案
  驱动（沿用 E7-3 驱动同构：pytest case 对单 API 栈 + worker）+
  随件修 standalone runner 语义；D2 = ③ E7-9 多进程栈断言（先解
  8000 口与 llm_gateway 冲突）；D3 = ④ E7-10 机制面 replay 驱动。
  计数纪律不变（op-4 随驱动落、manifest 零跑后改）；两笔裁定随 D1
  转录本节；夜窗（北京 21:50–24:00）不充证不变。时序：D1→D2→D3
  逐件合 → 重新冻结 head → r1 重跑 + B 核账（该轮才是收口材料）→
  §6 回填 → M5 收口归档；旧 r1 证据留过程账不凑数。
- **2026-10-12 B 核账后协调人升级裁定（standalone 语义等三项）**：
  - B 对 r1 的形态 1 核账通过并背书：E7-1 standalone「假红」定位为
    方法学假象（终末世界 = E7-3c 世界 + `verify.case()` 绝对账语义），
    E7-2「巧合绿」定位到期望画像逐字段同构——机制级推导成立。
  - **standalone 语义 = 逐案重播种重跑**：单案独立复核 = 重跑该
    pytest 案（自含 fresh world + 动作 + 案内 verify）；CLI
    `verify --case` 对动作案撤除（留 `--baseline`）；runbook §3
    「逐 case 核账」行重写。**不取终末世界模式**——软通过面即反复
    封杀的静默 skip 同族。
  - `verify.py` case() 内 `raw.pop("object_expectations")` 原地改写
    session 级 manifest dict（B nit，实位 :373）——D1 改 copy 取值。
  - **必修①撤回记录**：B 提案「fresh world 未清 `exports/` staging
    前缀、E7-1 单案重跑必假红」——协调人独立核验证伪：`seed.py:94-101`
    `_put_blobs` docstring 明写整桶 purge 且在 `apply_world` 链内，
    conftest `e7_fresh_world` 全路覆盖，该假红场景在现机制下不可能
    发生（B 只读了 `truncate_all` 的 DB 面未追对象面）。误报入过程
    台账：审方提案被协调人核验拦下——交叉验证系统生效的正面案例，
    与编码层 grep 案对称。
- **2026-10-13 D2 交付记录（A，随件转录）**：
  - 8000 口冲突解法：multi compose 既有 8100-8101 端口覆写即冻结
    路径（WSL llm_gateway 红线未动；宿主 8000/8100/8101/4318 实测
    空）。D2 补三处：`name: agenthu-multi` 钉项目名（否则合并文件
    落 dev 项目 `agenthu`，up 会重配置运行中 dev 栈的 db/redis/s3mock
    端口而非共存）；worker `volumes: !override []`（证据栈跑烤进
    镜像的已提交代码，不跑宿主 bind mount）；api/worker
    OPENAI_BASE_URL 默认指宿主 e6-replay
    （`host.docker.internal:9099/v1`，沿用证据期不接活 provider）。
  - 三项 BLOCKED_INVARIANTS（shared_rate_limit_not_doubled /
    trace_linkage / no_markers_in_telemetry）与驱动同 hunk 移入
    DRIVER_INVARIANTS（multi 世界单栈 verifier 不可达，驱动断言
    形态）；stub 真替换，E7-10 留 blocked。
  - 带出三件事实：① otel collector `0.116.0` 双发行版（core 与
    contrib）amd64 入口 ENOENT（distroless 缺 ELF 加载器一类），
    D2 改钉实证可用的 `0.111.0`；**alpha compose 同默认 0.116.0
    同病，非 D2 范围，提请协调人裁定修否**。② seed 的 agent run
    `decision_basis` 停在 M4 结构化 basis 之前的旧形状（messages
    序列化 500）——seed 随件修为现 schema，刻意不加新 marker()
    调用（token 顺序分配，插入会整体漂移）。③ provider 客户端
    span 名 = 裸 `POST`（现行 httpx 语义约定；URL 不进 span 名与
    属性——allowlist 生效的正面证据）。
  - op-4：E7-9 无 count_deltas（世界在 multi 独立 db）——「计数」=
    驱动侧限流边界（两 API 交替锤击 allowed==MAX 精确、两端口均
    见 429）/拓扑 2+2/泄漏扫描零命中（容器日志四面 + 运行期审计行
    `created_at > 起栈`；seed 审计 fixture 按设计带 marker 属删除案
    内容行，排除口径已写入驱动注记与 runbook §6）。
  - 验证（d2-dev7/d2-full1）：门控 12p+1 blocked-skip（E7-9 与
    11 案共存，无单栈扰动）；逐案 verify.json ok；CI 形状 555 恒
    总量、门脚本 exit 0；ruff/format/pyright 全 0。
