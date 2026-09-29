import { invoke } from "@tauri-apps/api/core";

interface NativeBackendResponse {
  status: number;
  headers: Record<string, string>;
  body: string;
}

/** B-4 受控转发：Backend 流量经 `backend_request`（Rust allowlist 校验、头
 *  白名单、无 Set-Cookie 透传）走 IPC，WebView CSP 无直连出口。仅 Tauri 运行
 *  时可用；开发浏览器模式沿用原生 fetch。 */
export async function backendFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const url = input instanceof Request ? input.url : input.toString();
  const headers = new Headers(init.headers);
  let body: string | null = null;
  if (typeof init.body === "string") body = init.body;
  else if (init.body != null) throw new Error("Backend 请求体必须是字符串（JSON）");
  const native = await invoke<NativeBackendResponse>("backend_request", {
    request: {
      url,
      method: init.method ?? "GET",
      headers: Object.fromEntries(headers.entries()),
      body,
    },
  });
  return new Response([204, 205, 304].includes(native.status) ? null : native.body, {
    status: native.status,
    headers: new Headers(native.headers),
  });
}
