# M4 运行时审计修复批次（α/β/γ 三片）

- 状态：进行中（§0 已冻结；α 实现中）
- 负责人：B（juefan-web；α/β/γ 归 B 依据负载平衡，不涉所有权变更）
- 分支：`fix/m4-audit-alpha` → `fix/m4-audit-beta` → `fix/m4-audit-gamma`（串行，三片各自独立 PR）
- 基线：main `c15a6dd`
- 依据：Gemini 报告审计 6/6 全部在 main 实锤（协调人复核采纳，行号与 main 精确对上）+ 协调人四条裁定（2026-10-08，本节原样转录）

## §0 执行框（实现前冻结；以下四条为协调人裁定原文转录）

### 裁定 1（缺陷 1 修法 → 片 α）

`_validate_arguments` 改 `async def`，`await provider.generate`，调用点 `:1038` 加 await。返回契约对齐调用点既有语义：修复成功返回 `(args, {"repaired_args": args})`（复活现成分支），失败维持 `(None, {"repaired": False})`；docstring 现在那段自相矛盾的文字一并改真。测试钉三点：async fake 返回修正 JSON 后校验通过（自愈真实生效）、失败路径不炸、用 `filterwarnings("error", category=RuntimeWarning)` 钉死无 "never awaited" 悬空协程。

病灶定位（main `c15a6dd` 实测）：`agent_runner.py:1255` 同步 `def`；`:1271` `provider.generate(` 无 await；`base.py:74` 协议为 `async def` → `repair` 是协程对象，`model_validate_json` 必抛 TypeError 被 `except Exception` 吞——自愈重试 100% 静默死亡 + 悬空协程告警；连带 `:1038` 调用点的 `schema_error.get("repaired_args")` 分支成为死码。全仓仅此一处病（`grounded_answers.py:300` 是正确 await）。

### 裁定 2（缺陷 2 修法——选型 a：上下文随 ModelTurn 走 → 片 β）

`ModelTurn` 增 `context` 字段（`input_text` / `instructions` / `tool_schemas`，有默认值，由 `generate_with_tools` 用 `dataclasses.replace` 填充）；`continue_with_tool_results` **签名不变**，replay 完整请求：原 prompt 作 input 首项 + function_call items + outputs + **`tools` 数组**，`store=False` 保持不可参数化。备选的改协议签名方案（b）会动 FakeProvider 和 agent_runner 调用点，爆炸半径更大，弃。隐私红线：context 仅进程内传递（本就是同进程组装的对象），**不得进日志/trace/span 属性**——注意与 #78 的 AllowlistSpanExporter 白名单纪律衔接。四-3 随本片：用注入 transport 钉请求体结构断言（tools 在场、store=False、input 含原 prompt、多轮 item 顺序）。

病灶定位：`openai_provider.py:234-260` 的 body 只有 `model/store/input`，input 仅含 function_call + outputs——无首轮 prompt/instructions、无 `tools` 数组；`store=False` 硬编码（D-033 冻结）= 服务端零状态 → 真 provider 下 Turn 2+ 是断头请求且无法再发起任何工具调用，`agent_max_model_turns` 循环（`:1148`）结构性坏死。掩盖机制：`test_m4_runtime.py` 全程 FakeProvider，`test_openai_provider.py` 7 个测试全在 embed/store 面，两工具方法零请求体覆盖。

### 裁定 3（缺陷 3 修法——方案 B：校验器分段 → 片 γ）

quote 按省略号（`……`/`…`/`...`）分段，各段在 haystack 内**按序** find（推进偏移），span 记首段起点→末段终点；提示词同步改准确表述（省略号仅限整段省略、不得改写字词），`PROMPT_VERSION` v1→v2。弃方案 A 的理由：提示词是已发布契约且模型必然自然产出省略号，禁令只会推高误剥率；B 方案每段仍逐字可定位，不弱化「引用必须真实存在、可定位」（AGENTS.md §3）。测试补：合法省略号引用存活、乱序分段剥除、某段不存在剥除。

病灶定位：`grounded_answers.py:44-51` 提示词示例自带 `……` 且明文「允许省略号缩短」；`:248-251` 纯 `find(normalized_quote)`——模型遵提示词即必然剥除，全剥时 `grounded=False` 合法回答被误判。9 个既有单测无省略号用例。

### 裁定 4（骑乘归属）

四-1（`_state_digest` 缺 `state_version`，低危：`:126` 定义不含、`:189` 调用方外挂、`:140` `_render_state` 直读 → 新调用方遗漏即 KeyError）随缺陷 2 片（同属 agent 上下文族）；四-2（`plan_validity` docstring "requires non-null" 在 #75 `.nullable()` 后失真，服务端双校验保留是对的，注释该改真）随缺陷 3 片（同属「契约文档改真」族）。

### 片划分与验收

| 片 | 内容 | 验收（各片独立 PR，CI 双跑绿 + head-bound 互审） |
|---|---|---|
| α | 裁定 1 全部 | 自愈真实生效实测（async fake 修正 JSON → 通过）；失败路径不炸；`filterwarnings("error", category=RuntimeWarning)` 下全绿（无悬空协程）；`repaired_args` 分支复活且有测试覆盖；docstring 改真；既有测试零回归 |
| β | 裁定 2 + 四-3 + 四-1 | 注入 transport 断言请求体：tools 在场、store=False、input 首项为原 prompt、多轮 item 顺序（function_call → function_call_output）；`continue_with_tool_results` 签名不变；context 不进日志/trace/span（白名单纪律衔接验证）；FakeProvider 兼容零改动；`_state_digest` 含 `state_version` 且调用方收敛；既有测试零回归 |
| γ | 裁定 3 + 四-2 | 合法省略号引用存活（分段按序定位）；乱序分段剥除；某段不存在剥除；span = 首段起点→末段终点；提示词改准 + `PROMPT_VERSION` v2；`plan_validity` docstring 改真；既有 9 测零回归 |

### 边界

- α/β/γ 与 #80（活雷② 文档）不冲突：`agent_runner.py` 在 #80 是文档引用，审计批次动 `:1038/:1255-1276` 实码——任一先合并无影响。
- 不混入无关重构；每片交付面最小化。
