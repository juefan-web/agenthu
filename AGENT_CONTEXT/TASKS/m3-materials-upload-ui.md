# M3 任务：讲解页课件上传入口（B 负责）

Status: open（2026-10-02 立项，协调人）。前置：#43 grounding 后端已合
main（`872c8b3`）；#44 讲解页 UI 待 A review（本任务在 #44 合并后开工，
worktree 沿用）。依据：`TASKS/m3-course-materials-privacy.md` §1/§4、
`TASKS/m3-materials-ingestion.md` §8（POST /v1/files 契约与 status
生命周期）。

## 1. 目标

用户能在打包客户端里把一门课的真实课件带进 grounding 管线：选课程 →
看到该课的文件列表 → 显式选择单个文件 → 上传 → 状态推进到 extracted、
chunks 出现在讲解页检索范围内。这是 M3 出口场景端到端成立的前提
（没有上传入口，E5 只能 API 造数）。

## 2. 文件列表来源裁定（协调人，2026-10-02）

隐私决策 §1 表把文件元数据事件（`study.material.discovered`）记为
「随采集自动」——**实现口径修正为：按需拉取、不进采集循环**。依据：
① AGENTS §3 最小化采集——用户只用一门课的 grounding 就不该全量采集
所有课的文件元数据；② 采集循环已因 learn 域 XSRF（D8）脆弱，不应把
grounding 功能耦合进采集稳定性；③ 不采集比采集更保守，方向与 §1 表
精神一致。`downloadUrl` 不进 Event 的约束不变（本来就是会话态）。
DECISIONS 已补 D-033 §1 实现注记；A/B 有异议在 review 本任务时提出。

## 3. 负责范围

1. **课程文件列表（按需）**：Tauri 命令经 vendored OneTHU learn 域拉
   当前课程文件列表（文件名/大小/时间），仅在用户停留在讲解页并选择
   课程时调用；失败透出（镜像 jar 的 XSRF 路径沿用 D8 修复）。
2. **下载 + 上传**：显式单文件动作 → Tauri 下载到临时目录 → 流式
   POST `/v1/files`（表单带 `course_name`）→ 上传完成**立即删本地
   临时文件**（§4：不留持久副本）。
3. **React 零字节接触**：React 只发命令、收状态；文件字节不进
   WebView（与 campus 采集同边界）。
4. **状态透出**：`FileRead.status` 生命周期（uploaded → extracted /
   unsupported_type / extraction_failed）在 UI 呈现；30s cron 兜底对
   用户透明（仅作为丢失 enqueue 的恢复路径）。
5. **同意门前置提示**：上传本身不需要 grounding consent（抽取是本地
   纯文本处理），但 embedding 需要——上传后、未同意课程下 chunks
   只做文本检索不嵌入的事实要在 UI 上如实标注（不暗示已开启）。

## 4. 不负责范围

- 后端任何改动（POST /v1/files 契约已冻结且 #41 已交付）。
- 批量上传、多选（单文件显式动作是隐私决策的字面要求，批量是后续项）。
- 移动端/Android（M6）。

## 5. 易错点（预埋）

- learn 域文件列表的字段口径先对一遍 vendor 实测返回再定 Zod 形状，
  别按想象写 schema。
- 临时文件删除要覆盖失败路径（上传失败也删；Windows 文件句柄未释放
  会删不掉——下载流关句柄后再传）。
- 上传大文件的超时与进度：`requestRaw` 走 Tauri IPC 代理，注意代理
   对 POST body 大小的实际行为，先实测一个 >10MB 课件再定是否需要
   分块或调超时。
- 别把文件列表缓存成全局状态（会话态数据，离开讲解页即弃）。

## 6. 验收标准

1. 打包客户端：选课 → 列表出现真实文件 → 选一个 → 上传成功 →
   status 到 extracted，讲解页对该课提问能命中其中内容。
2. 上传后临时目录无残留（含失败路径）。
3. React 层无文件字节（代码审查点 + 既有边界测试口径）。
4. learn 域失败（模拟 XSRF 失效）有明确错误提示，不静默空列表。
5. pnpm test/build、e2e typecheck 绿；新增用例覆盖列表拉取、上传
   表单字段（course_name）、临时清理。
