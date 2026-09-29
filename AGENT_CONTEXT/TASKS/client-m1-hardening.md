# 开发者 B：客户端加固清单（2026-09-29 细化）

主线任务见 `m1-1-assignment-event-derivation.md`（event 载荷时区修复 + 派生
任务展示）。本文件是 B 的独立任务，来源为首轮仓库审阅与四轮验收中确认仍未
关闭的客户端开放项，按风险排序。全部在 `feature/*` 分支从 main 拉出。

## B-1（高）：同步协调器 single-flight + 重试上限

- 现状：`EventSyncCoordinator.flush` 无并发保护，采集完成、`online` 事件、
  手动重试三个入口可并发 flush（双份上传靠服务端幂等兜底、cursor 可能被旧
  响应交错覆盖）；失败批无 attempt 计数与退避。
- 输出：single-flight；失败批重试上限 + 指数退避 + 超限可见提示（不再无限
  全量重试）；回归测试（并发入口、批间失败断点续传、超限停发）。
- 背景：round-4 已实测 100 条/批，真实数据量增长后这是最先暴露的风险。

## B-2（高）：SQLite 连接 busy_timeout / 复用

- 现状：`lib.rs` 每次 invoke 新开 `Connection` 且无 busy handler，采集 flush、
  手动重试、online 监听可并发打队列命令（"database is locked" 风险）。
- 输出：`busy_timeout` + WAL（或连接复用）；`lib.rs` 队列命令测试补齐
  （含并发与坏行隔离既有用例回归）。

## B-3（中）：会话与入队防线的边角

1. `campus_restore` 版本不兼容快照自清理（当前返回 Err 不清理，用户每次启动
   死循环直到重登）——清理 + 明确引导文案。
2. `assertSafeEvent` 改为无条件执行（当前未配置 Backend 的直接入队路径
   `App.tsx` 绕过敏感字段检查）。

## B-4（中）：`backendUrl` 运行时配置

- 现状：仅构建期 `VITE_BACKEND_URL`，换环境需重新构建；CSP guard 要求源
  显式加白，运行时配置需与 guard/`tauri.conf.json` 联动设计。
- 输出：设置界面或首启配置 + CSP 白名单机制说明（如何在不重新构建的前提
  下安全放行非本地 Backend 源——与 A 对齐安全模型后动手）。

## B-5（中低）：测试纵深

1. Testing Library 覆盖登录/2FA 状态机（方式选择、双轮提示、错误透出、
   原地重试、恢复/登出）——目前全靠构建包人工验收。
2. Playwright（CDP 驱动构建包）主链冒烟：登录 → 采集 → 同步 → 计划 →
   Focus。round-4 验收脚本已证明 CDP 驱动可行，沉淀为可重复测试可大幅降低
   每轮人工成本。

## 继续暂缓（维持既有决策）

- Android 凭据存储/通知/同步恢复（P1 后段）。
- OneTHU BSL 1.1、LearnX 及依赖许可逐文件分发审查——**发布前必须完成**，
  发布节点前一个里程碑启动。
