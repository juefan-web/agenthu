import { describe, expect, it } from "vitest";
import { dataGenerationKey, readDataGeneration, writeDataGeneration } from "./generation";

function storage(): Storage {
  const map = new Map<string, string>();
  return {
    getItem: (k: string) => map.get(k) ?? null,
    setItem: (k: string, v: string) => void map.set(k, v),
    removeItem: (k: string) => void map.delete(k),
  } as Storage;
}

describe("data generation storage (owner-scoped)", () => {
  it("round-trips per owner under namespaced keys", () => {
    const s = storage();
    writeDataGeneration(s, "owner-a", 3);
    writeDataGeneration(s, "owner-b", 5);
    expect(readDataGeneration(s, "owner-a")).toBe(3);
    expect(readDataGeneration(s, "owner-b")).toBe(5);
    expect(dataGenerationKey("owner-a")).toBe("agenthu.data-generation:owner-a");
  });

  it("null owner or null value never auto-fills (compat window)", () => {
    const s = storage();
    expect(readDataGeneration(s, null)).toBeNull();
    writeDataGeneration(s, "owner-a", null);
    expect(readDataGeneration(s, "owner-a")).toBeNull();
    expect(s.getItem(dataGenerationKey("owner-a"))).toBeNull();
  });

  it("rejects garbage values by reading null", () => {
    const s = storage();
    s.setItem(dataGenerationKey("owner-a"), "not-a-number");
    expect(readDataGeneration(s, "owner-a")).toBeNull();
    s.setItem(dataGenerationKey("owner-a"), "0");
    expect(readDataGeneration(s, "owner-a")).toBeNull();
  });
});
