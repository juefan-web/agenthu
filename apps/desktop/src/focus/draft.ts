import { FocusSessionSchema, type FocusSession } from "@agenthu/contracts";
import { invoke } from "@tauri-apps/api/core";
import { z } from "zod";
import { isTauriRuntime } from "../adapters/campus/tauriTransport";

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

export class LocalFocusDraftStore implements FocusDraftStore {
  constructor(private readonly storage: Storage | null = typeof localStorage === "undefined" ? null : localStorage) {}

  async read(): Promise<FocusDraft | null> {
    const raw = this.storage?.getItem("agenthu.focus-draft");
    if (!raw) return null;
    try {
      return FocusDraftSchema.parse(JSON.parse(raw));
    } catch {
      return null;
    }
  }

  async write(draft: FocusDraft | null): Promise<void> {
    if (draft) this.storage?.setItem("agenthu.focus-draft", JSON.stringify(FocusDraftSchema.parse(draft)));
    else this.storage?.removeItem("agenthu.focus-draft");
  }
}

export class SqliteFocusDraftStore implements FocusDraftStore {
  private writes: Promise<void> = Promise.resolve();

  async read(): Promise<FocusDraft | null> {
    await this.writes;
    const draft = await invoke<unknown>("focus_get_draft");
    return draft === null ? null : FocusDraftSchema.parse(draft);
  }

  write(draft: FocusDraft | null): Promise<void> {
    const checked = draft === null ? null : FocusDraftSchema.parse(draft);
    const next = this.writes.then(() => invoke<void>("focus_set_draft", { draft: checked }));
    this.writes = next.catch(() => undefined);
    return next;
  }
}

export function createFocusDraftStore(): FocusDraftStore {
  return isTauriRuntime() ? new SqliteFocusDraftStore() : new LocalFocusDraftStore();
}
