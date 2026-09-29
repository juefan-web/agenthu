/**
 * 清华 WebVPN（网瑞达 Wrdvpn）URL 编解码 —— 已与真实门户逐字符对齐验证。
 *
 * 规则（docs/architecture.md §2）：
 * - AES-128-CFB（CFB-128 整块反馈，不是 CFB-8）
 * - Key = IV = "wrdvpnisthebest!"
 * - 编码：hostname 尾部补 '0' 至 16 倍数 → 加密 → hex(IV) + hex(密文).slice(0, 2×原长)
 * - URL：https://webvpn.tsinghua.edu.cn/{http|https}/{编码host}{path}{query}
 */
import aesjs from "aes-js";

export const WEBVPN_ROOT = "https://webvpn.tsinghua.edu.cn";
const KEY = aesjs.utils.utf8.toBytes("wrdvpnisthebest!");
const IV = aesjs.utils.utf8.toBytes("wrdvpnisthebest!");
const IV_HEX = aesjs.utils.hex.fromBytes(IV); // "77726476706e69737468656265737421"

function newCipher(): { encrypt(p: Uint8Array): Uint8Array; decrypt(c: Uint8Array): Uint8Array } {
  // segmentSize=16 → CFB-128，与 Node crypto 的 aes-128-cfb 一致
  return new aesjs.ModeOfOperation.cfb(KEY, IV, 16);
}

function padToBlock(bytes: Uint8Array, padByte = 0x30): Uint8Array {
  const rem = bytes.length % 16;
  if (rem === 0) return bytes;
  const out = new Uint8Array(bytes.length + (16 - rem));
  out.set(bytes);
  out.fill(padByte, bytes.length);
  return out;
}

/** 编码主机名 → hex（含 IV 前缀） */
export function encryptHost(hostname: string): string {
  const plain = padToBlock(aesjs.utils.utf8.toBytes(hostname));
  const cipher = newCipher().encrypt(plain);
  return IV_HEX + aesjs.utils.hex.fromBytes(cipher).slice(0, hostname.length * 2);
}

/** 解码 hex（含 IV 前缀）→ 主机名 */
export function decryptHost(hexWithIv: string): string {
  const body = hexWithIv.slice(IV_HEX.length);
  const byteLen = body.length / 2;
  const padded = padToBlock(aesjs.utils.hex.toBytes(body));
  const plain = newCipher().decrypt(padded).slice(0, byteLen);
  return aesjs.utils.utf8.fromBytes(plain).replace(/0+$/, "");
}

/** 任意 URL → WebVPN URL */
export function encodeUrl(target: string): string {
  const url = new URL(target);
  const proto = url.protocol === "http:" ? "http" : "https";
  return `${WEBVPN_ROOT}/${proto}/${encryptHost(url.hostname)}${url.pathname}${url.search}${url.hash}`;
}

/** WebVPN URL → 原始 URL；非 WebVPN URL 原样返回 */
export function decodeUrl(maybeWebvpn: string): string | null {
  const url = new URL(maybeWebvpn);
  if (url.hostname !== "webvpn.tsinghua.edu.cn") return null;
  const parts = url.pathname.split("/").filter(Boolean);
  const proto = parts[0];
  const encoded = parts[1];
  if (!proto || !encoded) return null;
  const rest = parts.slice(2);
  try {
    const host = decryptHost(encoded);
    return `${proto}://${host}/${rest.join("/")}${url.search}${url.hash}`;
  } catch {
    return null;
  }
}

/**
 * 双重包装自愈：`…/https/<hexA>/https/<hexB>/…` → 只保留**最内层**那一层包装。
 *
 * 真机事故：learn 页面经 webvpn 取回时，wengine 已把页面里的链接改写成 `/https/<hex>/…`，
 * 而 LEARN_PREFIX 本身就是包装后的 learn 根，再拼一次就成了两层包装，服务端 404
 * （通知附件的预览与下载全废）。解析处已经不会再拼错，这里是兜底：**任何**路径拼错
 * 都不该以 404 收场，宁可自愈成最内层那一层。
 */
export function normalizeWebvpnUrl(url: string): string {
  const m = /^https?:\/\/webvpn\.tsinghua\.edu\.cn\/(.*)$/i.exec(url);
  if (!m) return url;
  const path = m[1]!;
  const hits = [...path.matchAll(/https\/[0-9a-f]{16,}\//gi)];
  if (hits.length <= 1) return url;
  const last = hits[hits.length - 1]!;
  return `${WEBVPN_ROOT}/${path.slice(last.index ?? 0)}`;
}

/** HttpClient.webVPNEncoder 的默认实现 */
export function webvpnWrap(url: string): string {
  const healed = normalizeWebvpnUrl(url);
  if (healed.startsWith(WEBVPN_ROOT)) return healed;
  try {
    return encodeUrl(healed);
  } catch {
    return healed;
  }
}
