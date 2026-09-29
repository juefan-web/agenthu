# 技术决策

## 2026-09-26：客户端采用 React/Tauri，OneTHU 进入本地 CampusAdapter

- 客户端采用 React + TypeScript + Vite + Tauri 2 + Rust，Windows 优先，Android 复用同一前端。
- OneTHU 固定 vendor commit `2e3455fc235719b7f91fffaf5fe35e09220dda73`，首期只复制 `@onethu/core`。
- OneTHU 的网络请求由 Tauri transport 承载；React 页面只依赖 `CampusAdapter`，不导入 `@onethu/core`。
- 课程、作业、课表和校历先映射为 Agenthu Event，再交给 Backend；Backend 是跨设备事实源。
- 默认不保存校园密码，2FA 验证码不落盘、不进入 Event 和日志。Stronghold 已注册，但 Session/Cookie 持久化尚未接通；上线前必须完成并验证这一边界。
- GOALS.md 作为产品构想参考，不复制为运行时规范。
