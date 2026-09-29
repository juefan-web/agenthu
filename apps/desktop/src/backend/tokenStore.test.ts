import { describe, expect, it } from "vitest";
import { LocalTokenStore, StoredTokenSchema } from "./tokenStore";

function storage(): Storage {
  const values = new Map<string, string>();
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => { values.set(key, value); },
    removeItem: (key) => { values.delete(key); },
  } as Storage;
}

const token = { access_token: "jwt-1", expires_at: "2026-10-01T00:00:00.000Z" };

describe("LocalTokenStore", () => {
  it("round-trips a validated token", async () => {
    const store = new LocalTokenStore(storage());
    await store.write(token);
    expect(await store.read()).toEqual(token);
    await store.clear();
    expect(await store.read()).toBeNull();
  });

  it("discards malformed persisted tokens", async () => {
    const data = storage();
    data.setItem("agenthu.backend-token", JSON.stringify({ access_token: "" }));
    expect(await new LocalTokenStore(data).read()).toBeNull();
    expect(data.getItem("agenthu.backend-token")).toBeNull();
  });

  it("requires an offset-bearing expiry timestamp", () => {
    expect(StoredTokenSchema.safeParse({ ...token, expires_at: "not-a-date" }).success).toBe(false);
  });
});