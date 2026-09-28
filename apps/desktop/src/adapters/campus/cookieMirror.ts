import type { CookieJar, CookieRecord } from "@onethu/core";

/** campus_request 回传的只读 Cookie 镜像条目（Rust 权威仓的投影）。
 *  仅 *.tsinghua.edu.cn 的 host/name/value 三元组——原始 Set-Cookie 头与其余
 *  属性（Expires/HttpOnly/SameSite 等）一律不跨 IPC（隐私边界见 CURRENT_STATE）。 */
export interface MirroredCookie {
  host: string;
  name: string;
  value: string;
  hostOnly: boolean;
}

function isCampusHost(host: string): boolean {
  return host === "tsinghua.edu.cn" || host.endsWith(".tsinghua.edu.cn");
}

function domainMatch(host: string, domain: string, hostOnly: boolean): boolean {
  if (host === domain) return true;
  return !hostOnly && host.endsWith(`.${domain}`);
}

function pathMatch(requestPath: string, cookiePath: string): boolean {
  if (requestPath === cookiePath) return true;
  if (requestPath.startsWith(cookiePath)) {
    return cookiePath.endsWith("/") || requestPath[cookiePath.length] === "/";
  }
  return false;
}

/** host → (name → record)。镜像读取方是 vendored 适配层的域内逻辑：
 *  InfoClient #csrfToken（webvpn 域 XSRF-TOKEN）与 #wengineCookieDance 的
 *  setRaw 注入；请求附 Cookie 仍由 Rust 每跳完成（transport 过滤 Cookie 头）。 */
const buckets = new Map<string, Map<string, CookieRecord>>();

/** campus_request 响应到达后、Promise resolve 前调用：以权威投影整体替换**出现
 *  在本轮投影里**的 host 的镜像条目（Rust 总是回传受影响 host 的全量 cookie，
 *  故 host 内的过期/删除以本轮为准）。空数组不触碰任何 host；整仓清空由
 *  logout 链路的 jar.clear() 完成（session.reset）。 */
export function applyCampusCookieMirror(cookies: MirroredCookie[]): void {
  const touched = new Set<string>();
  for (const cookie of cookies) {
    const host = cookie.host.toLowerCase();
    if (isCampusHost(host)) touched.add(host);
  }
  for (const host of touched) buckets.delete(host);
  for (const cookie of cookies) {
    const host = cookie.host.toLowerCase();
    if (!isCampusHost(host)) continue;
    const bucket = buckets.get(host) ?? new Map<string, CookieRecord>();
    bucket.set(cookie.name, {
      name: cookie.name, value: cookie.value, domain: host, path: "/",
      hostOnly: cookie.hostOnly, secure: false,
    });
    buckets.set(host, bucket);
  }
}

/** 挂给 HttpClient 的 jar：读走镜像，写仅限 dance 的 setRaw；custody 在 Rust。 */
export function campusCookieJar(): CookieJar {
  return {
    getCookies: (url) => {
      const host = url.hostname.toLowerCase();
      const out: CookieRecord[] = [];
      for (const bucket of buckets.values()) {
        for (const rec of bucket.values()) {
          if (rec.secure && url.protocol !== "https:") continue;
          if (!domainMatch(host, rec.domain, rec.hostOnly)) continue;
          if (!pathMatch(url.pathname, rec.path)) continue;
          out.push(rec);
        }
      }
      return out;
    },
    setRaw: (url, setCookieLine) => {
      // wengine dance：GET_COOKIE_URL 响应体解析出的 name=value 对注入本域。
      const pair = setCookieLine.split(";")[0] ?? "";
      const eq = pair.indexOf("=");
      if (eq <= 0) return;
      const name = pair.slice(0, eq).trim();
      const value = pair.slice(eq + 1).trim();
      const host = url.hostname.toLowerCase();
      if (!name || !isCampusHost(host)) return;
      const bucket = buckets.get(host) ?? new Map<string, CookieRecord>();
      bucket.set(name, { name, value, domain: host, path: "/", hostOnly: true, secure: false });
      buckets.set(host, bucket);
    },
    // Set-Cookie 不经 WebView 响应头；镜像只由 applyCampusCookieMirror 投影。
    setFromResponse() {},
    serialize: () => "[]",
    hydrate() {},
    clear: (domainSuffix) => {
      if (!domainSuffix) {
        buckets.clear();
        return;
      }
      for (const host of [...buckets.keys()]) {
        if (host === domainSuffix || host.endsWith(`.${domainSuffix}`)) buckets.delete(host);
      }
    },
  };
}
