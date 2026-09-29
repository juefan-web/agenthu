import { describe, expect, it } from "vitest";
import { applyCampusCookieMirror, campusCookieJar, redactCampusDebugLine } from "./cookieMirror";

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

  it("redacts token-shaped values from debug lines but keeps cookie names and URLs", () => {
    // cookie 名单原样保留（值不出现）
    expect(redactCampusDebugLine("[HTTP-WENGINE] cookies=wengine_vpn_ticket,XSRF-TOKEN body(1024)=…"))
      .toContain("cookies=wengine_vpn_ticket,XSRF-TOKEN");
    // 令牌形长值（cookie 值 / CAS ticket / _csrf）遮蔽
    expect(redactCampusDebugLine("XSRF-TOKEN=AbCdEf012345678901234567")).not.toContain("AbCdEf012345678901234567");
    expect(redactCampusDebugLine("?_csrf=Z0FxYjRzNWw4OHJnNHF6ZDR2ZTF3ZWR4"))
      .not.toContain("Z0FxYjRzNWw4OHJnNHF6ZDR2ZTF3ZWR4");
    expect(redactCampusDebugLine("ticket=ST-1234567890abcdefghijklmnopqrstu")).not.toContain("ST-1234567890");
    // URL（含 ://、点、斜杠）不匹配令牌形态，原样保留
    const urlLine = "final=https://learn.tsinghua.edu.cn/b/j_spring_security_thauth_roaming_entry?ticket=x1";
    expect(redactCampusDebugLine(urlLine)).toContain("https://learn.tsinghua.edu.cn");
    // 超长行（wengine body 转储，含空格分段不做值级 redact）截断
    const long = "[HTTP-WENGINE] body=" + "seg1 seg2 seg3 ".repeat(400);
    const truncated = redactCampusDebugLine(long);
    expect(truncated.length).toBeLessThanOrEqual(4013);
    expect(truncated.endsWith("…<truncated>")).toBe(true);
  });
});
