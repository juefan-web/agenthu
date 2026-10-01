import type { FormEvent } from "react";
import { useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { useQueryClient } from "@tanstack/react-query";
import { isTauriRuntime } from "../../adapters/campus/tauriTransport";
import { errorText } from "../../lib/errors";
import { BACKEND_URL_PREFERENCE_KEY, useServices } from "../../app/services";

/** Backend 登录 + 运行时源切换（B-4）两块表单。仅在已配置源且未登录时渲染。 */
export function BackendForms({ onNotice }: { onNotice: (message: string) => void }) {
  const { backend, backendSession, buildTimeBackendUrl } = useServices();
  const [backendEmail, setBackendEmail] = useState("");
  const [backendPassword, setBackendPassword] = useState("");
  const [backendBusy, setBackendBusy] = useState(false);
  const [backendOriginInput, setBackendOriginInput] = useState(buildTimeBackendUrl);
  const [backendOriginBusy, setBackendOriginBusy] = useState(false);
  const queryClient = useQueryClient();

  async function backendLogin(event: FormEvent) {
    event.preventDefault();
    if (!backend) return;
    setBackendBusy(true);
    const email = backendEmail;
    const password = backendPassword;
    setBackendPassword("");
    try {
      await backendSession?.login(email, password);
      onNotice("Backend 已连接");
      await queryClient.invalidateQueries();
    } catch (error) { onNotice(errorText(error)); }
    finally { setBackendBusy(false); }
  }

  /** B-4 运行时源切换：Rust 侧先验证并入 allowlist，持久化偏好后重载生效
   *  （校验失败即拒，不落任何状态）。清空输入则回落构建期默认。 */
  async function saveBackendOrigin(event: FormEvent) {
    event.preventDefault();
    setBackendOriginBusy(true);
    try {
      const trimmed = backendOriginInput.trim().replace(/\/$/, "");
      if (!trimmed) {
        localStorage.removeItem(BACKEND_URL_PREFERENCE_KEY);
      } else {
        if (isTauriRuntime()) await invoke("backend_origin_add", { origin: new URL(trimmed).origin });
        localStorage.setItem(BACKEND_URL_PREFERENCE_KEY, trimmed);
      }
      window.location.reload();
    } catch (error) {
      onNotice(`Backend 地址无法使用：${errorText(error)}`);
      setBackendOriginBusy(false);
    }
  }

  return <>
    <form className="backend-login" onSubmit={(event) => void saveBackendOrigin(event)}>
      <label>Backend 地址<input type="url" value={backendOriginInput} onChange={(event) => setBackendOriginInput(event.target.value)} placeholder={buildTimeBackendUrl || "https://api.example.com"} /></label>
      <button className="ghost-button" disabled={backendOriginBusy}>{backendOriginBusy ? "保存中…" : "保存并重载"}</button>
    </form>
    <form className="backend-login" onSubmit={(event) => void backendLogin(event)}>
      <label>Backend 邮箱<input type="email" value={backendEmail} onChange={(event) => setBackendEmail(event.target.value)} required /></label>
      <label>Backend 密码<input type="password" value={backendPassword} onChange={(event) => setBackendPassword(event.target.value)} required /></label>
      <button className="primary-button" disabled={backendBusy}>{backendBusy ? "登录中…" : "登录 Backend"}</button>
    </form>
  </>;
}
