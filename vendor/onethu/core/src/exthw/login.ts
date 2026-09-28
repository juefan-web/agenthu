/**
 * 外部作业源登录客户端（雨课堂 / TUOJ 系 / Tyche / DSA OJ）。
 *
 * 目标：一般用户**不需要手动爬 Cookie** —— 各平台用自己的账号体系登录，登录成功后
 * 由本模块从**传输层自定义头**里取回会话 Cookie，拼成后续只读拉取所需的 `Cookie:` 串。
 *
 * ⚠️ 浏览器读不到真正的 `Set-Cookie`（fetch 规范屏蔽），OneTHU 的 Tauri 传输层
 * （`lib/transport.ts` 的 `tauriFetch`）把每一跳的 Set-Cookie 显式放进：
 *   - `x-onethu-set-cookie`      ：JSON 字符串数组（全部 Set-Cookie 原文）
 *   - `x-onethu-set-cookie-hops` ：`[{u,l}]`（带 host 的逐跳记录，取 `l`）
 * 本模块优先读前者，缺失时回退后者。**浏览器预览环境下两者都不存在 → 登录必然失败**
 * （会给出明确提示），登录只在桌面端可用。
 *
 * 只读：登录仅为拿到会话，不做任何写操作。
 */
import type { FetchLike } from "../http.js";
import { BASE as TUOJ_BASE } from "./tuoj.js";
import { BASE as DSA_BASE } from "./dsa.js";
import { BASE as TYCHE_BASE, basicHeader } from "./tyche.js";

const YKT_BASE = "https://pro.yuketang.cn";
const UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/79.0.3945.88 Safari/537.36";

/** 登录结果：拼好的 Cookie 串（直接可用于拉取） */
export interface ExtHwLoginResult {
  cookie: string;
}

/* ── Set-Cookie 取回（走 OneTHU 传输层自定义头） ── */

/** 从响应头取回本次请求产生的全部 Set-Cookie 原文 */
function readSetCookies(res: Response): string[] {
  const out: string[] = [];
  const raw = res.headers.get("x-onethu-set-cookie");
  if (raw) {
    try {
      const arr = JSON.parse(raw) as unknown;
      if (Array.isArray(arr)) for (const x of arr) if (typeof x === "string") out.push(x);
    } catch {
      /* 容忍非法 JSON */
    }
  }
  if (out.length === 0) {
    const hops = res.headers.get("x-onethu-set-cookie-hops");
    if (hops) {
      try {
        const arr = JSON.parse(hops) as unknown;
        if (Array.isArray(arr)) {
          for (const h of arr) {
            const l = (h as { l?: unknown } | null)?.l;
            if (typeof l === "string") out.push(l);
          }
        }
      } catch {
        /* 容忍非法 JSON */
      }
    }
  }
  return out;
}

/** Set-Cookie 原文数组 → `name=value; …`（同名后者覆盖，忽略属性段） */
function cookiePairs(setCookies: string[]): Map<string, string> {
  const m = new Map<string, string>();
  for (const sc of setCookies) {
    const semi = sc.indexOf(";");
    const head = semi >= 0 ? sc.slice(0, semi) : sc;
    const eq = head.indexOf("=");
    if (eq <= 0) continue;
    const name = head.slice(0, eq).trim();
    const value = head.slice(eq + 1).trim();
    if (name) m.set(name, value);
  }
  return m;
}

function serialize(m: Map<string, string>): string {
  return [...m].map(([k, v]) => `${k}=${v}`).join("; ");
}

/**
 * 从一次响应里取回本次产生的全部 Set-Cookie，解析成 name→value。
 * 复用传输层自定义头通道（见文件头说明），供各登录流程（含扫码登录）统一调用。
 */
export function captureCookies(res: Response): Map<string, string> {
  return cookiePairs(readSetCookies(res));
}

/** 雨课堂清华站点固定字段（缺失时补齐；拉取端 authCookie 亦会兜底） */
const YKT_FIXED_COOKIES: ReadonlyArray<readonly [string, string]> = [
  ["xtbz", "ykt"],
  ["platform_type", "0"],
  ["platform_id", "3"],
  ["django_language", "zh-cn"],
  ["uv_id", "2598"],
  ["university_id", "2598"],
];

/**
 * 雨课堂登录成功后的统一出口：把 Set-Cookie（原文数组或已解析的 name→value）
 * 补齐固定字段后序列化为可直接用于拉取的 `Cookie:` 串。
 */
export function yuketangBuildCookie(setCookiesOrPairs: string[] | Map<string, string>): string {
  const pairs = Array.isArray(setCookiesOrPairs) ? cookiePairs(setCookiesOrPairs) : setCookiesOrPairs;
  for (const [k, v] of YKT_FIXED_COOKIES) if (!pairs.has(k)) pairs.set(k, v);
  return serialize(pairs);
}

/** 桌面端传输层未提供 set-cookie 通道时的统一提示（浏览器预览的必然结果） */
function noCookieError(sourceName: string): Error {
  return new Error(
    `${sourceName} 登录未取回会话 Cookie：浏览器预览读不到 Set-Cookie，请在桌面端（Tauri）使用登录功能。`,
  );
}

async function postJson(
  fetchLike: FetchLike,
  url: string,
  body: unknown,
  headers: Record<string, string>,
): Promise<{ res: Response; json: Record<string, unknown> | null; text: string }> {
  const res = await fetchLike(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "User-Agent": UA, Accept: "application/json, text/plain, */*", ...headers },
    body: JSON.stringify(body),
  });
  const text = await res.text();
  let json: Record<string, unknown> | null = null;
  try {
    json = JSON.parse(text) as Record<string, unknown>;
  } catch {
    json = null;
  }
  return { res, json, text };
}

/* ── 雨课堂（手机号 + 短信验证码） ── */

/** 第一步：发送短信验证码。成功返回 void；失败 throw（带服务端 msg）。 */
export async function yuketangSendSmsCode(mobile: string, fetchLike: FetchLike): Promise<void> {
  const phone = mobile.trim();
  if (!phone) throw new Error("请输入手机号");
  const { json } = await postJson(
    fetchLike,
    `${YKT_BASE}/pc/login/send_sms_login_code/`,
    { mobile: phone, login: "phone", hcaptcha_token: "", randstr: "", ticket: "" },
    { Origin: YKT_BASE, Referer: `${YKT_BASE}/` },
  );
  if (!json) throw new Error("雨课堂发送验证码返回非 JSON");
  if (json["success"] !== true) {
    const msg = typeof json["msg"] === "string" ? json["msg"] : `status_code=${String(json["status_code"] ?? "?")}`;
    throw new Error(`发送验证码失败：${msg}`);
  }
}

/** 第二步：用验证码登录，返回可用的 Cookie 串（已补清华固定字段）。 */
export async function yuketangVerifyLogin(
  mobile: string,
  code: string,
  fetchLike: FetchLike,
): Promise<ExtHwLoginResult> {
  const phone = mobile.trim();
  const pwd = code.trim();
  if (!phone) throw new Error("请输入手机号");
  if (!pwd) throw new Error("请输入验证码");
  const { res, json } = await postJson(
    fetchLike,
    `${YKT_BASE}/pc/login/verify_pwd_login/`,
    { type: "PC", name: phone, pwd },
    { Origin: YKT_BASE, Referer: `${YKT_BASE}/` },
  );
  if (!json) throw new Error("雨课堂登录返回非 JSON");
  if (json["success"] !== true) {
    const msg = typeof json["msg"] === "string" ? json["msg"] : `status_code=${String(json["status_code"] ?? "?")}`;
    throw new Error(`登录失败：${msg}`);
  }
  const pairs = captureCookies(res);
  if (pairs.size === 0) throw noCookieError("雨课堂");
  // 清华站点固定字段补齐（见 yuketangBuildCookie）
  return { cookie: yuketangBuildCookie(pairs) };
}

/* ── TUOJ 系（用户名 + 密码；AI 版 / 经典版仅 base 不同） ── */

/** POST {base}/api/user/login {username,password}；成功 Set-Cookie session / session.sig。
 *  R15 20.2：`base` 缺省 AI 版；经典版传 `TUOJ_CLASSIC_BASE`。 */
export async function tuojLogin(
  username: string,
  password: string,
  fetchLike: FetchLike,
  base: string = TUOJ_BASE,
): Promise<ExtHwLoginResult> {
  const u = username.trim();
  if (!u) throw new Error("请输入 TUOJ 用户名");
  if (!password) throw new Error("请输入 TUOJ 密码");
  const { res, json } = await postJson(
    fetchLike,
    `${base}/api/user/login`,
    { username: u, password },
    { Origin: base, Referer: `${base}/` },
  );
  const pairs = cookiePairs(readSetCookies(res));
  if (pairs.size === 0) {
    const err = json && typeof json["error"] === "string" ? json["error"] : `HTTP ${res.status}`;
    throw new Error(`TUOJ 登录失败：${err}`);
  }
  return { cookie: serialize(pairs) };
}

/* ── DSA OJ（邮箱 + 密码；老式 form-urlencoded） ── */

/**
 * POST `user.php` `{action:"login", username:<邮箱>, password}`；成功 `{error:0}` 并
 * Set-Cookie 会话。R15 20.2：DSA 无统一认证，仅手动账密。
 */
export async function dsaLogin(
  email: string,
  password: string,
  fetchLike: FetchLike,
): Promise<ExtHwLoginResult> {
  const u = email.trim();
  if (!u) throw new Error("请输入 DSA OJ 邮箱");
  if (!password) throw new Error("请输入 DSA OJ 密码");
  const res = await fetchLike(`${DSA_BASE}user.php`, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
      "User-Agent": UA,
      Accept: "application/json, text/plain, */*",
      Origin: "https://dsa.cs.tsinghua.edu.cn",
      Referer: DSA_BASE,
    },
    body: new URLSearchParams({ action: "login", username: u, password }).toString(),
  });
  const text = await res.text();
  let json: Record<string, unknown> | null = null;
  try {
    json = JSON.parse(text) as Record<string, unknown>;
  } catch {
    json = null;
  }
  // 先看业务错误码（error≠0 时即使有 Set-Cookie 也不算登录成功）
  const code = json ? Number(json["error"]) : 0;
  if (json && Number.isFinite(code) && code !== 0) {
    const msg = typeof json["message"] === "string" ? json["message"] : `error=${code}`;
    throw new Error(`DSA OJ 登录失败：${msg}`);
  }
  const pairs = captureCookies(res);
  if (pairs.size === 0) throw noCookieError("DSA OJ");
  return { cookie: serialize(pairs) };
}

/* ── Tyche（用户名 + 密码；外层 Basic 已硬编码） ── */

/** SHA-1 十六进制（Tyche 登录口令变换：sha1(sha1(password) + token)） */
async function sha1Hex(s: string): Promise<string> {
  const subtle = globalThis.crypto?.subtle;
  if (!subtle) throw new Error("当前环境缺少 SHA-1 能力（WebCrypto 不可用），请在桌面端使用");
  const buf = await subtle.digest("SHA-1", new TextEncoder().encode(s));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** Tyche returnFailString → 中文（对齐 Login.html 内嵌 JS 的映射） */
const TYCHE_FAIL: Record<string, string> = {
  username_not_exist: "用户名不存在",
  password_mismatch: "密码错误",
  already_logged_in: "当前已经登录，请先退出当前账户",
  lock_ip_check_fail: "检测到异常登录请求（考场锁定），请联系考场老师",
  token_mismatch: "登录令牌不匹配，请重试",
};

/**
 * POST user/Login（form 编码）；成功 Set-Cookie JSESSIONID / username / uid。
 *
 * 对齐 Login.html 内嵌 JS（2026-09-18 实测）：
 * 1. `GET user/GetToken?username=<u>` → `{ vcode, token }`（无 Set-Cookie，token 即挑战值）
 * 2. 口令变换 `password = sha1(sha1(明文口令) + token)`（服务端存 sha1(口令) 做挑战应答）
 * 3. `POST user/Login` 带 `username / password / token`
 * ⚠️ vcode **通常不必填**（Login.html 默认 `$('#vcode-field').hide()`，仅 GetToken 返回
 * `vcode:true` 的考场锁定账号才需要）——那种情况本函数直接报错，请走「高级：手填 Cookie」。
 */
export async function tycheLogin(
  username: string,
  password: string,
  fetchLike: FetchLike,
): Promise<ExtHwLoginResult> {
  const u = username.trim();
  if (!u) throw new Error("请输入 Tyche 用户名");
  if (!password) throw new Error("请输入 Tyche 密码");
  const authHeaders = { Authorization: basicHeader(""), "User-Agent": UA, Accept: "application/json, text/plain, */*" };

  // ① 取挑战 token
  const tokenRes = await fetchLike(`${TYCHE_BASE}/user/GetToken?username=${encodeURIComponent(u)}`, {
    method: "GET",
    headers: authHeaders,
  });
  const tokenText = await tokenRes.text();
  let tokenJson: Record<string, unknown> | null = null;
  try {
    tokenJson = JSON.parse(tokenText) as Record<string, unknown>;
  } catch {
    tokenJson = null;
  }
  if (!tokenJson || tokenJson["status"] !== "success" || typeof tokenJson["token"] !== "string") {
    const fail = typeof tokenJson?.["returnFailString"] === "string" ? String(tokenJson["returnFailString"]) : "";
    throw new Error(`Tyche 登录失败：${(TYCHE_FAIL[fail] ?? fail) || `获取登录令牌失败（HTTP ${tokenRes.status}）`}（校外需 sslvpn，勿用 webvpn）`);
  }
  if (tokenJson["vcode"] === true) {
    throw new Error("Tyche 该账号当前需要验证码（考场锁定），无法免人工登录——请用「高级：手动粘贴 Cookie」");
  }
  const token = tokenJson["token"];

  // ② 口令变换 + 登录
  const hashed = await sha1Hex((await sha1Hex(password)) + token);
  const form = new URLSearchParams({ username: u, password: hashed, token }).toString();
  const res = await fetchLike(`${TYCHE_BASE}/user/Login`, {
    method: "POST",
    headers: { ...authHeaders, "Content-Type": "application/x-www-form-urlencoded" },
    body: form,
  });
  const text = await res.text();
  let json: Record<string, unknown> | null = null;
  try {
    json = JSON.parse(text) as Record<string, unknown>;
  } catch {
    json = null;
  }
  const pairs = cookiePairs(readSetCookies(res));
  if (pairs.size === 0) {
    const fail = json && typeof json["returnFailString"] === "string" ? String(json["returnFailString"]) : "";
    throw new Error(`Tyche 登录失败：${(TYCHE_FAIL[fail] ?? fail) || `HTTP ${res.status}`}（校外需 sslvpn，勿用 webvpn）`);
  }
  return { cookie: serialize(pairs) };
}
