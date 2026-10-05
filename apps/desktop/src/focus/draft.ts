import { FocusSessionSchema, type FocusSession } from "@agenthu/contracts";
import { invoke } from "@tauri-apps/api/core";
import { z } from "zod";
import { isTauriRuntime } from "../adapters/campus/tauriTransport";
import { focusDraftKey, isolateLegacyUnownedStorage, UNOWNED_OWNER } from "../sync/owner";

const FocusDraftSchema = z.object({
  session: FocusSessionSchema,
  note: z.string(),
});

export interface FocusDraft {
  session: FocusSession;
  note: string;
}

export interface FocusDraftStore {
  read(): Promise<FocusDraft | null>;
  write(draft: FocusDraft | null): Promise<void>;
}

export interface OwnerScopedStoreOptions {
  storage?: Storage | null;
  /** P0-2（D-036）：每次操作现解当前 owner；null → unowned。草稿按账号
   *  命名空间存取，切账号后另一账号的草稿既不可见也不被清除。 */
  resolveOwner?: () => string | null;
}

function isStorageLike(value: Storage | OwnerScopedStoreOptions): value is Storage {
  return typeof (value as Storage).getItem === "function" && typeof (value as Storage).setItem === "function";
}

export class LocalFocusDraftStore implements FocusDraftStore {
  private readonly storage: Storage | null;
  private readonly resolveOwner: () => string | null;

  constructor(options: Storage | OwnerScopedStoreOptions = {}) {
    const normalized = isStorageLike(options) ? { storage: options } : options;
    this.storage = normalized.storage === undefined
      ? (typeof localStorage === "undefined" ? null : localStorage)
      : normalized.storage;
    this.resolveOwner = normalized.resolveOwner ?? (() => null);
    isolateLegacyUnownedStorage(this.storage);
  }

  private key(): string {
    return focusDraftKey(this.resolveOwner() ?? UNOWNED_OWNER);
  }

  async read(): Promise<FocusDraft | null> {
    const raw = this.storage?.getItem(this.key());
    if (!raw) return null;
    try {
      return FocusDraftSchema.parse(JSON.parse(raw));
    } catch {
      return null;
    }
  }

  async write(draft: FocusDraft | null): Promise<void> {
    if (draft) this.storage?.setItem(this.key(), JSON.stringify(FocusDraftSchema.parse(draft)));
    else this.storage?.removeItem(this.key());
  }
}

export class SqliteFocusDraftStore implements FocusDraftStore {
  private writes: Promise<void> = Promise.resolve();
  private readonly resolveOwner: () => string | null;

  constructor(options: { resolveOwner?: () => string | null } = {}) {
    this.resolveOwner = options.resolveOwner ?? (() => null);
  }

  private owner(): string {
    return this.resolveOwner() ?? UNOWNED_OWNER;
  }

  async read(): Promise<FocusDraft | null> {
    await this.writes;
    const draft = await invoke<unknown>("focus_get_draft", { owner: this.owner() });
    return draft === null ? null : FocusDraftSchema.parse(draft);
  }

  write(draft: FocusDraft | null): Promise<void> {
    const checked = draft === null ? null : FocusDraftSchema.parse(draft);
    const next = this.writes.then(() => invoke<void>("focus_set_draft", { draft: checked, owner: this.owner() }));
    this.writes = next.catch(() => undefined);
    return next;
  }
}

export function createFocusDraftStore(options: { resolveOwner?: () => string | null } = {}): FocusDraftStore {
  return isTauriRuntime() ? new SqliteFocusDraftStore(options) : new LocalFocusDraftStore(options);
}
