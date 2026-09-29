import { useState, type FormEvent } from "react";
import { isTauriRuntime } from "../adapters/campus/tauriTransport";
import type { SessionStatus } from "../adapters/campus/types";
import { campus } from "../campus/instance";
import { useSessionStore } from "../state/session";

/** 会话状态 → 全局 store 的唯一映射（外壳的采集错误处理与组件内部共用）。 */
export function applySession(status: SessionStatus): void {
  useSessionStore.getState().setTwoFactor(
    status.state === "need-2fa" ? status.methods : [],
    status.state === "need-2fa" && !!status.codeSent,
    status.state === "need-2fa" ? status.selectedMethod : undefined,
    status.state === "need-2fa" ? status.notice : undefined,
  );
  useSessionStore.getState().setStatus(
    status.state,
    status.username,
    status.state === "error" ? status.message : null,
  );
}

export function CampusConnection({ onError }: { onError: (error: unknown) => void }) {
  const { status, message, methods, codeSent, selectedMethod, notice } = useSessionStore();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [method, setMethod] = useState("totp");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [trustDevice, setTrustDevice] = useState(false);
  const activeMethod = methods.includes(method) ? method : methods[0] ?? "";

  async function login(event: FormEvent) {
    event.preventDefault(); setBusy(true);
    const input = { username, password }; setPassword("");
    try { applySession(await campus.login(input)); }
    catch (error) { onError(error); }
    finally { setBusy(false); }
  }
  async function verify(event: FormEvent) {
    event.preventDefault(); setBusy(true);
    const input = { method: selectedMethod, code, trustDevice }; setCode("");
    try { applySession(await campus.verify2fa(input)); }
    catch (error) { onError(error); }
    finally { setBusy(false); }
  }
  async function sendCode() {
    setBusy(true);
    try { applySession(await campus.send2fa(activeMethod)); }
    catch (error) { onError(error); }
    finally { setBusy(false); }
  }
  async function cancel() {
    setBusy(true);
    try { await campus.logout(); useSessionStore.getState().reset(); setCode(""); }
    catch (error) { onError(error); }
    finally { setBusy(false); }
  }
  async function retryVerification() {
    setBusy(true);
    try {
      const status = await campus.retryTwoFactor();
      if (status) applySession(status);
    } catch (error) { onError(error); }
    finally { setBusy(false); }
  }
  if (status === "ready") return <p className="connected-message">校园会话已连接，可采集最新数据。</p>;
  if (!isTauriRuntime()) return <p className="empty-state">校园登录仅在 Tauri 客户端中可用。</p>;
  return <>
    {message && <p className="error-text" role="alert">{message}</p>}
    {status === "need-2fa" && notice && <p className="empty-state" role="status">{notice}</p>}
    {status === "error" && campus.canRetryTwoFactor() && <div className="section-actions"><button type="button" className="primary-button" disabled={busy} onClick={() => void retryVerification()}>重试验证（免重输密码）</button></div>}
    {status === "need-2fa" ? <form className="inline-form" onSubmit={(event) => void verify(event)}>
      <label>验证方式<select value={codeSent ? selectedMethod : activeMethod} disabled={busy || codeSent} onChange={(event) => setMethod(event.target.value)}>{methods.map((item) => <option key={item} value={item}>{({ totp: "TOTP", mobile: "短信", wechat: "企业微信" } as Record<string, string>)[item] ?? item}</option>)}</select></label>
      {!codeSent && <button type="button" className="primary-button" disabled={busy || !activeMethod} onClick={() => void sendCode()}>{activeMethod === "totp" ? "使用验证器" : "发送验证码"}</button>}
      {codeSent && <><label>验证码<input value={code} onChange={(event) => setCode(event.target.value)} autoComplete="one-time-code" required /></label><label className="checkbox-label"><input type="checkbox" checked={trustDevice} onChange={(event) => setTrustDevice(event.target.checked)} />信任此设备</label><button className="primary-button" disabled={busy}>验证</button></>}
      <button type="button" className="ghost-button" onClick={() => void cancel()}>取消</button>
    </form> : <form className="inline-form" onSubmit={(event) => void login(event)}>
      <label>学号<input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" required /></label>
      <label>密码<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" required /></label>
      <button className="primary-button" disabled={busy}>登录</button>
    </form>}
  </>;
}
