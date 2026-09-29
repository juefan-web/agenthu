import { invoke } from "@tauri-apps/api/core";
import { z } from "zod";
import { isTauriRuntime } from "../adapters/campus/tauriTransport";

/**
 * Access tokens are short lived and must not be readable by other origins or
 * persisted in plain text. In Tauri they live in an encrypted Stronghold
 * snapshot; the browser development fallback keeps them in sessionStorage so
 * they disappear when the tab closes.
 */
export const StoredTokenSchema = z.object({
  access_token: z.string().min(1),
  expires_at: z.string().datetime({ offset: true }),
});

export type StoredToken = z.infer<typeof StoredTokenSchema>;

export interface TokenStore {
  read(): Promise<StoredToken | null>;
  write(token: StoredToken): Promise<void>;
  clear(): Promise<void>;
}

const STORAGE_KEY = "agenthu.backend-token";

export class LocalTokenStore implements TokenStore {
  constructor(
    private readonly storage: Storage | null = typeof sessionStorage === "undefined" ? null : sessionStorage,
  ) {}

  async read(): Promise<StoredToken | null> {
    const raw = this.storage?.getItem(STORAGE_KEY);
    if (!raw) return null;
    try {
      return StoredTokenSchema.parse(JSON.parse(raw));
    } catch {
      this.storage?.removeItem(STORAGE_KEY);
      return null;
    }
  }

  async write(token: StoredToken): Promise<void> {
    this.storage?.setItem(STORAGE_KEY, JSON.stringify(StoredTokenSchema.parse(token)));
  }

  async clear(): Promise<void> {
    this.storage?.removeItem(STORAGE_KEY);
  }
}

export class StrongholdTokenStore implements TokenStore {
  async read(): Promise<StoredToken | null> {
    const raw = await invoke<string | null>("backend_token_get");
    if (!raw) return null;
    try { return StoredTokenSchema.parse(JSON.parse(raw)); }
    catch { await this.clear(); return null; }
  }

  async write(token: StoredToken): Promise<void> {
    await invoke<void>("backend_token_set", { token: JSON.stringify(StoredTokenSchema.parse(token)) });
  }

  async clear(): Promise<void> {
    await invoke<void>("backend_token_clear");
  }
}

export function createTokenStore(): TokenStore {
  return isTauriRuntime() ? new StrongholdTokenStore() : new LocalTokenStore();
}
