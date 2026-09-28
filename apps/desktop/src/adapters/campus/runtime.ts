import {
  CampusSession,
  HttpClient,
  InfoClient,
  LearnClient,
  webvpnWrap,
} from "@onethu/core";
import { OneThuCampusAdapter } from "./onethuAdapter";
import { campusCookieJar } from "./cookieMirror";
import { createTauriAuthGateway } from "./tauriAuthGateway";
import { tauriFetch } from "./tauriTransport";

/** 官方包现场诊断（默认关闭）：构建期 VITE_CAMPUS_DEBUG=1 或运行期在 DevTools
 *  设 localStorage["agenthu.campus-debug"]="1" 后重载。输出 vendored 的
 *  LEARN-SILENT/INFO 诊断行（cookie 名与截断 URL，不含值）。 */
function campusDebugEnabled(): boolean {
  return import.meta.env.VITE_CAMPUS_DEBUG === "1"
    || (typeof localStorage !== "undefined" && localStorage.getItem("agenthu.campus-debug") === "1");
}

export function createCampusRuntime() {
  const http = new HttpClient({
    fetch: (url, init) => tauriFetch(url, init),
    // custody 在 Rust 原生仓；这里挂只读镜像 jar（campus_request 载荷回填），
    // 供 vendored InfoClient 的 XSRF 读取与 wengine dance 注入使用。
    jar: campusCookieJar(),
  });
  http.webVPNEncoder = webvpnWrap;
  if (campusDebugEnabled()) http.debug = (line) => console.debug(`[campus] ${line}`);
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
