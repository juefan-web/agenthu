/** X-Data-Generation 的 owner 命名空间持久化（P0-4，D-036 §8-3）。
 *  批推响应捕获 live 代际 → 下批回发；409 generation_stale 后置 null
 *  进入兼容窗（不带头 = 重新对齐，服务端恒在响应头回当前值）。
 *  代际是顺序提示而非身份：未登录（无 owner）读 null，绝不自动补值。 */

export function dataGenerationKey(ownerKey: string): string {
  return `agenthu.data-generation:${ownerKey}`;
}

export function readDataGeneration(storage: Storage | null, ownerKey: string | null): number | null {
  if (!storage || ownerKey === null) return null;
  const raw = storage.getItem(dataGenerationKey(ownerKey));
  if (raw === null) return null;
  const value = Number(raw);
  return Number.isSafeInteger(value) && value >= 1 ? value : null;
}

export function writeDataGeneration(
  storage: Storage | null,
  ownerKey: string | null,
  value: number | null,
): void {
  if (!storage || ownerKey === null) return;
  if (value === null) storage.removeItem(dataGenerationKey(ownerKey));
  else storage.setItem(dataGenerationKey(ownerKey), String(value));
}
