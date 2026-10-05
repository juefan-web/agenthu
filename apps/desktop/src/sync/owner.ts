/**
 * P0-2（D-036）：本地存储的 owner 命名空间。
 *
 * 冻结契约（B 稿 §4）：owner_key = canonical backend origin + server
 * user_id，哈希后作存储键；无主历史行隔离，禁止自动归当前账号或重传，
 * 由用户明确决定处理（adopt/discard），「本地删除不清另一账号」。
 *
 * ownerKey 不是安全边界（user_id 本身不可猜且非敏感），哈希只为存储键
 * 卫生：可读 origin/userId 不进键名。因此采用自包含的同步 SHA-256 实现
 * ——确定性必须跨环境绝对稳定（WebView/jsdom/Node 任一实现差异都会让
 * 同一账号落到两个命名空间），不值得为它引入 subtleCrypto 的异步性与
 * 环境差异。
 */

/** 未登录 / 未归属数据的命名空间常量：legacy 键与未登录采集都归这里。 */
export const UNOWNED_OWNER = "unowned";

export const LEGACY_QUEUE_KEY = "agenthu.event-queue";
export const LEGACY_CORRUPT_KEY = "agenthu.event-queue.corrupt";
export const LEGACY_FOCUS_DRAFT_KEY = "agenthu.focus-draft";

export function queueKey(ownerKey: string): string {
  return `agenthu.event-queue:${ownerKey}`;
}

export function queueCorruptKey(ownerKey: string): string {
  return `agenthu.event-queue:${ownerKey}:corrupt`;
}

export function focusDraftKey(ownerKey: string): string {
  return `agenthu.focus-draft:${ownerKey}`;
}

/** 无主（owner 维度出现前的历史键）一次性隔离到 unowned 命名空间。
 * 幂等：目标键已存在时不动源键（避免覆盖既有隔离结果）；目标不存在才
 * 搬迁。搬完后源键移除——此后所有读写都只见命名空间键。 */
export function isolateLegacyUnownedStorage(storage: Storage | null | undefined): void {
  if (!storage) return;
  moveIfTargetAbsent(storage, LEGACY_QUEUE_KEY, queueKey(UNOWNED_OWNER));
  moveIfTargetAbsent(storage, LEGACY_CORRUPT_KEY, queueCorruptKey(UNOWNED_OWNER));
  moveIfTargetAbsent(storage, LEGACY_FOCUS_DRAFT_KEY, focusDraftKey(UNOWNED_OWNER));
}

function moveIfTargetAbsent(storage: Storage, legacy: string, target: string): void {
  const value = storage.getItem(legacy);
  if (value === null) return;
  if (storage.getItem(target) === null) {
    storage.setItem(target, value);
  }
  storage.removeItem(legacy);
}

// --- SHA-256（自包含同步实现；FIPS 180-4，测试向量钉住正确性） ---

const K = [
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
];

function sha256Hex(input: string): string {
  const bytes = new TextEncoder().encode(input);
  const bitLength = bytes.length * 8;
  const padded = new Uint8Array((((bytes.length + 8) >> 6) + 1) << 6);
  padded.set(bytes);
  padded[bytes.length] = 0x80;
  const view = new DataView(padded.buffer);
  view.setUint32(padded.length - 4, bitLength >>> 0);
  view.setUint32(padded.length - 8, Math.floor(bitLength / 0x1_0000_0000));

  let h0 = 0x6a09e667, h1 = 0xbb67ae85, h2 = 0x3c6ef372, h3 = 0xa54ff53a;
  let h4 = 0x510e527f, h5 = 0x9b05688c, h6 = 0x1f83d9ab, h7 = 0x5be0cd19;
  const w = new Uint32Array(64);

  for (let offset = 0; offset < padded.length; offset += 64) {
    for (let i = 0; i < 16; i += 1) w[i] = view.getUint32(offset + i * 4);
    for (let i = 16; i < 64; i += 1) {
      const s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >>> 3);
      const s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >>> 10);
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0;
    }
    let a = h0, b = h1, c = h2, d = h3, e = h4, f = h5, g = h6, h = h7;
    for (let i = 0; i < 64; i += 1) {
      const s1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
      const ch = (e & f) ^ (~e & g);
      const temp1 = (h + s1 + ch + K[i] + w[i]) >>> 0;
      const s0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const temp2 = (s0 + maj) >>> 0;
      h = g; g = f; f = e; e = (d + temp1) >>> 0;
      d = c; c = b; b = a; a = (temp1 + temp2) >>> 0;
    }
    h0 = (h0 + a) >>> 0; h1 = (h1 + b) >>> 0; h2 = (h2 + c) >>> 0; h3 = (h3 + d) >>> 0;
    h4 = (h4 + e) >>> 0; h5 = (h5 + f) >>> 0; h6 = (h6 + g) >>> 0; h7 = (h7 + h) >>> 0;
  }
  return [h0, h1, h2, h3, h4, h5, h6, h7].map((word) => word.toString(16).padStart(8, "0")).join("");
}

function rotr(value: number, bits: number): number {
  return ((value >>> bits) | (value << (32 - bits))) >>> 0;
}

/** ownerKey = SHA-256(`${origin}\n${userId}`) 的前 16 个 hex 字符。
 * origin 必须是规范形（`new URL(baseUrl).origin`）；相同校园账号 ≠ 相同
 * Backend 账号——不同 origin / 不同 userId 即不同 owner。 */
export function deriveOwnerKey(origin: string, userId: string): string {
  return sha256Hex(`${origin}\n${userId}`).slice(0, 16);
}

export { sha256Hex };
