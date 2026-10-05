import { describe, expect, it } from "vitest";
import {
  deriveOwnerKey,
  focusDraftKey,
  isolateLegacyUnownedStorage,
  queueCorruptKey,
  queueKey,
  sha256Hex,
  UNOWNED_OWNER,
} from "./owner";

function storage(): Storage {
  const values = new Map<string, string>();
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => { values.set(key, value); },
    removeItem: (key) => { values.delete(key); },
  } as Storage;
}

describe("sha256Hex", () => {
  it("matches the FIPS 180-4 test vectors", () => {
    expect(sha256Hex("")).toBe("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
    expect(sha256Hex("abc")).toBe("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
    // 多块输入（一百万个 a）：跨块调度、填充与 64 位长度域的经典向量
    expect(sha256Hex("a".repeat(1_000_000))).toBe("cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0");
  });
});

describe("deriveOwnerKey (P0-2 / D-036)", () => {
  it("is deterministic and differs per origin and per user", () => {
    const a = deriveOwnerKey("https://api.example.com", "user-1");
    expect(a).toHaveLength(16);
    expect(a).toBe(deriveOwnerKey("https://api.example.com", "user-1"));
    expect(a).not.toBe(deriveOwnerKey("https://api.example.com", "user-2"));
    expect(a).not.toBe(deriveOwnerKey("https://api.other.org", "user-1"));
  });
});

describe("storage keys", () => {
  it("namespaces queue, corrupt backup, and focus draft per owner", () => {
    expect(queueKey("abc123")).toBe("agenthu.event-queue:abc123");
    expect(queueCorruptKey("abc123")).toBe("agenthu.event-queue:abc123:corrupt");
    expect(focusDraftKey("abc123")).toBe("agenthu.focus-draft:abc123");
    expect(queueKey(UNOWNED_OWNER)).toBe("agenthu.event-queue:unowned");
  });
});

describe("isolateLegacyUnownedStorage", () => {
  it("moves legacy keys to the unowned namespace exactly once", () => {
    const data = storage();
    data.setItem("agenthu.event-queue", JSON.stringify({ events: [], cursor: "c1" }));
    data.setItem("agenthu.event-queue.corrupt", "backup-1");
    data.setItem("agenthu.focus-draft", "draft-1");

    isolateLegacyUnownedStorage(data);

    expect(data.getItem("agenthu.event-queue")).toBeNull();
    expect(data.getItem("agenthu.event-queue:unowned")).toContain("c1");
    expect(data.getItem("agenthu.event-queue:unowned:corrupt")).toBe("backup-1");
    expect(data.getItem("agenthu.focus-draft:unowned")).toBe("draft-1");
    expect(data.getItem("agenthu.focus-draft")).toBeNull();
  });

  it("never overwrites an existing unowned namespace (idempotent)", () => {
    const data = storage();
    data.setItem("agenthu.event-queue", "legacy-late");
    data.setItem("agenthu.event-queue:unowned", "already-isolated");

    isolateLegacyUnownedStorage(data);

    expect(data.getItem("agenthu.event-queue:unowned")).toBe("already-isolated");
    expect(data.getItem("agenthu.event-queue")).toBeNull();
  });
});
