import { queueCorruptKey, queueKey } from "../../sync/owner";
import { readDataGeneration, writeDataGeneration } from "../../sync/generation";

/** B 稿 §3 本机清理状态机：not_started → cleaning（删除确认成功立即
 *  进入）→ verified / failed；failed 允许显式重试，期间冻结旧队列。
 *  verified 判据 = 可复跑的检查输出（键存在性 / 行数 / 槽位清点），
 *  不是一次性手工确认——服务端 COMPLETED ≠ 本机 verified。
 *  回执槽独立于清理面（90 天凭证），永不在本矩阵中清除。 */

export type LocalCleanupState = "not_started" | "cleaning" | "verified" | "failed";

export interface CleanupCheck {
  name: string;
  ok: boolean;
  detail: string;
}

export interface LocalCleanupRecord {
  state: LocalCleanupState;
  checks: CleanupCheck[] | null;
  updated_at: string;
  error?: string;
}

export function cleanupStorageKey(ownerKey: string): string {
  return `agenthu.local-cleanup:${ownerKey}`;
}

export function readCleanupRecord(storage: Storage | null, ownerKey: string): LocalCleanupRecord | null {
  try {
    const raw = storage?.getItem(cleanupStorageKey(ownerKey));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<LocalCleanupRecord>;
    if (parsed.state !== "cleaning" && parsed.state !== "verified" && parsed.state !== "failed" && parsed.state !== "not_started") {
      return null;
    }
    return { state: parsed.state, checks: parsed.checks ?? null, updated_at: parsed.updated_at ?? "", error: parsed.error };
  } catch {
    return null;
  }
}

export function writeCleanupRecord(storage: Storage | null, ownerKey: string, record: LocalCleanupRecord): void {
  try {
    storage?.setItem(cleanupStorageKey(ownerKey), JSON.stringify(record));
  } catch {
    // 清理记录写不进存储不阻断清理本身；状态面以 UI 内存态为准
  }
}

/** 探针注入面：view 层按环境组装（Tauri = SQLite/Rust 命令，Web =
 * localStorage 键面），本模块只编排状态机与判据，可全量单测。 */
export interface LocalCleanupDeps {
  clearQueueData(ownerKey: string): Promise<number>;
  countQueueData(ownerKey: string): Promise<number>;
  clearDraft(ownerKey: string): Promise<void>;
  draftPresent(ownerKey: string): Promise<boolean>;
  logoutSession(): Promise<void>;
  /** null = 当前环境无持久业务 token 面（跳过并如实标注）。 */
  tokenPresent(): Promise<boolean | null>;
  storage: Storage | null;
}

export async function runCleanupChecks(deps: LocalCleanupDeps, ownerKey: string): Promise<CleanupCheck[]> {
  const checks: CleanupCheck[] = [];

  const queueRows = await deps.countQueueData(ownerKey);
  checks.push({ name: "待同步队列行数", ok: queueRows === 0, detail: `本 owner 剩余 ${queueRows} 行` });

  if (deps.storage) {
    const queueKeyPresent = deps.storage.getItem(queueKey(ownerKey)) !== null;
    const corruptKeyPresent = deps.storage.getItem(queueCorruptKey(ownerKey)) !== null;
    checks.push({ name: "队列存储键", ok: !queueKeyPresent && !corruptKeyPresent, detail: queueKeyPresent || corruptKeyPresent ? "键仍存在" : "已清除" });
  }

  const draft = await deps.draftPresent(ownerKey);
  checks.push({ name: "Focus 草稿", ok: !draft, detail: draft ? "草稿仍在" : "已清除" });

  const generation = deps.storage ? readDataGeneration(deps.storage, ownerKey) : null;
  checks.push({ name: "数据代际标记", ok: generation === null, detail: generation === null ? "已清除" : "仍残留" });

  const token = await deps.tokenPresent();
  checks.push(
    token === null
      ? { name: "业务凭据", ok: true, detail: "当前环境无持久凭据面，未检查" }
      : { name: "业务凭据", ok: !token, detail: token ? "仍残留" : "已清除" },
  );

  // 信息行（恒 ok）：回执槽独立保留——90 天凭证不随本机清理清除
  checks.push({ name: "回执槽", ok: true, detail: "独立保留（90 天凭证；不随本机清理清除）" });
  return checks;
}

function checksPassed(checks: CleanupCheck[]): boolean {
  return checks.every((check) => check.ok);
}

export async function runLocalCleanup(deps: LocalCleanupDeps, ownerKey: string): Promise<LocalCleanupRecord> {
  const write = (record: LocalCleanupRecord) => writeCleanupRecord(deps.storage, ownerKey, record);
  write({ state: "cleaning", checks: null, updated_at: new Date().toISOString() });
  try {
    await deps.logoutSession();
    const removed = await deps.clearQueueData(ownerKey);
    await deps.clearDraft(ownerKey);
    writeDataGeneration(deps.storage, ownerKey, null);
    const checks = await runCleanupChecks(deps, ownerKey);
    const record: LocalCleanupRecord = {
      state: checksPassed(checks) ? "verified" : "failed",
      checks,
      updated_at: new Date().toISOString(),
    };
    if (record.state === "failed") record.error = `清理后 ${removed} 行被清除，但检查未全过`;
    write(record);
    return record;
  } catch (cause) {
    const record: LocalCleanupRecord = {
      state: "failed",
      checks: null,
      updated_at: new Date().toISOString(),
      error: cause instanceof Error ? cause.message : String(cause),
    };
    write(record);
    return record;
  }
}

/** failed 的显式重试 / verified 的重新核账共用入口（可复跑）。 */
export async function retryLocalCleanup(deps: LocalCleanupDeps, ownerKey: string): Promise<LocalCleanupRecord> {
  return runLocalCleanup(deps, ownerKey);
}

export function cleanupStateText(state: LocalCleanupState): string {
  switch (state) {
    case "not_started":
      return "尚未开始";
    case "cleaning":
      return "正在清理本机数据";
    case "verified":
      return "本机清理已核验";
    case "failed":
      return "本机清理未完成";
    default:
      return state;
  }
}
