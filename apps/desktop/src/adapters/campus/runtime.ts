import {
  CampusSession,
  HttpClient,
  InfoClient,
  LearnClient,
  webvpnWrap,
} from "@onethu/core";
import { OneThuCampusAdapter } from "./onethuAdapter";
import { createTauriAuthGateway } from "./tauriAuthGateway";
import { tauriFetch } from "./tauriTransport";

export function createCampusRuntime() {
  const http = new HttpClient({
    fetch: (url, init) => tauriFetch(url, init),
    // Cookies stay in Rust; the vendor jar is intentionally inert.
    jar: { getCookies: () => [], setFromResponse() {}, setRaw() {}, serialize: () => "[]", hydrate() {}, clear() {} },
  });
  http.webVPNEncoder = webvpnWrap;
  const learn = new LearnClient(http);
  const info = new InfoClient(http);
  const session = new CampusSession({
    http,
    learn,
    info,
    fetchLike: (url, init) => tauriFetch(url, init),
  });
  const auth = createTauriAuthGateway();
  // learn 静默重登路径二的账密源（路径一 /f/login SSO 失败时启用）：
  // 仅登录链存续的内存凭据期间供应；指纹/受信凭据取自登录链 helper，
  // 不用 session 里的展示指纹——两者分叉会把设备身份打散。
  learn.credentialProvider = () => auth.silentReloginCredentials();
  // Only the adapter crosses this boundary. The raw session (cookies,
  // credential accessors) stays private to the runtime wiring.
  return { adapter: new OneThuCampusAdapter({ session, auth }) };
}
