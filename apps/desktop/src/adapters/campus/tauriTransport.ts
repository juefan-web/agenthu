import { invoke } from "@tauri-apps/api/core";
import { applyCampusCookieMirror, type MirroredCookie } from "./cookieMirror";

interface NativeResponse {
  status: number;
  headers: Record<string, string>;
  body: string;
  finalUrl: string;
  cookies: MirroredCookie[];
}

export function isTauriRuntime(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

function bodyToString(body: BodyInit | null | undefined): string | undefined {
  if (body === null || body === undefined) return undefined;
  if (typeof body === "string") return body;
  if (body instanceof URLSearchParams) return body.toString();
  if (body instanceof FormData) {
    const params = new URLSearchParams();
    for (const [key, value] of body.entries()) {
      if (typeof value !== "string") throw new Error("校园数据首期不支持通过 transport 上传文件");
      params.set(key, value);
    }
    return params.toString();
  }
  throw new Error("不支持的校园请求体类型");
}

export async function tauriFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  if (!isTauriRuntime()) throw new Error("校园请求需要 Tauri 客户端");
  const url = input instanceof Request ? input.url : input.toString();
  const headers = new Headers(init.headers);
  if ((init.body instanceof URLSearchParams || init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/x-www-form-urlencoded;charset=UTF-8");
  }
  const native = await invoke<NativeResponse>("campus_request", {
    request: {
      url,
      method: init.method ?? "GET",
      headers: Object.fromEntries(headers.entries()),
      body: bodyToString(init.body),
      redirect: init.redirect ?? "follow",
    },
  });
  // 镜像在 resolve 前并入：vendored 读取方（Info XSRF）在同一轮
  // 请求→dance→重读的时序里就能看到本轮权威投影。
  applyCampusCookieMirror(native.cookies ?? []);
  const responseHeaders = new Headers(native.headers);
  responseHeaders.set("x-onethu-final-url", native.finalUrl);
  const response = new Response([204, 205, 304].includes(native.status) ? null : native.body, { status: native.status, headers: responseHeaders });
  Object.defineProperty(response, "url", { value: native.finalUrl });
  return response;
}
