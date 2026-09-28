import { describe, expect, it } from "vitest";
import { applyCampusCookieMirror, campusCookieJar } from "./cookieMirror";

/** vendored INFO_PREFIX 同款包装 URL：host 落在 webvpn.tsinghua.edu.cn。 */
const INFO_URL = "https://webvpn.tsinghua.edu.cn/https/77726476706e69737468656265737421f9f9479369247b59700f81b9991b2631506205de/b/info/gxfw_fg/common/grjbxx";

function xsrf(url: string): string | undefined {
  return campusCookieJar().getCookies(new URL(url)).find((c) => c.name === "XSRF-TOKEN")?.value;
}

describe("campus cookie mirror jar", () => {
  it("serves mirrored cookies to the info-domain XSRF reader with host isolation", () => {
    applyCampusCookieMirror([
      { host: "webvpn.tsinghua.edu.cn", name: "XSRF-TOKEN", value: "fixture-token", hostOnly: true },
      { host: "learn.tsinghua.edu.cn", name: "JSESSIONID", value: "learn-session", hostOnly: true },
    ]);
    expect(xsrf(INFO_URL)).toBe("fixture-token");
    const webvpnCookies = campusCookieJar().getCookies(new URL(INFO_URL));
    expect(webvpnCookies.some((c) => c.name === "JSESSIONID")).toBe(false);
  });

  it("supports the wengine dance: empty mirror → setRaw injection → read", () => {
    campusCookieJar().clear();
    applyCampusCookieMirror([]);
    expect(xsrf(INFO_URL)).toBeUndefined();
    // dance 从 GET_COOKIE_URL 响应体解析出的 name=value 对注入 webvpn 域
    campusCookieJar().setRaw(new URL("https://webvpn.tsinghua.edu.cn/"), "XSRF-TOKEN=danced-token; Path=/");
    expect(xsrf(INFO_URL)).toBe("danced-token");
  });

  it("replaces a host wholesale from the authoritative projection", () => {
    applyCampusCookieMirror([{ host: "webvpn.tsinghua.edu.cn", name: "XSRF-TOKEN", value: "stale", hostOnly: true }]);
    applyCampusCookieMirror([{ host: "webvpn.tsinghua.edu.cn", name: "OTHER", value: "fresh", hostOnly: true }]);
    const names = campusCookieJar().getCookies(new URL(INFO_URL)).map((c) => c.name);
    expect(names).toEqual(["OTHER"]);
  });

  it("matches domain-wide mirrors across subdomains", () => {
    applyCampusCookieMirror([{ host: "tsinghua.edu.cn", name: "wide", value: "fanout", hostOnly: false }]);
    expect(campusCookieJar().getCookies(new URL(INFO_URL)).some((c) => c.name === "wide")).toBe(true);
  });

  it("ignores non-campus hosts and clears on demand", () => {
    applyCampusCookieMirror([{ host: "evil.example.com", name: "XSRF-TOKEN", value: "nope", hostOnly: true }]);
    expect(campusCookieJar().getCookies(new URL("https://evil.example.com/"))).toHaveLength(0);
    campusCookieJar().clear();
    expect(campusCookieJar().getCookies(new URL(INFO_URL))).toHaveLength(0);
  });
});
