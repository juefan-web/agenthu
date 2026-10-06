import { describe, expect, it, vi } from "vitest";
import { invoke } from "@tauri-apps/api/core";
import { MemoryReceiptStore, StrongholdReceiptStore, type StoredReceipt } from "./receiptStore";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));

const receipt: StoredReceipt = {
  capability: "cap-token-0123456789abcdef",
  receipt_id: "0b6a6c8e-4a1c-4c2a-9d3e-1234567890ab",
  client_request_id: "confirm-key-0001",
  confirm_body: {
    preview_id: "c47ac1b7-4d5a-4b8e-8f2a-3d1c9e7b5a11",
    preview_digest: "a".repeat(64),
    client_request_id: "confirm-key-0001",
    confirmed: true,
  },
  issued_at: "2026-10-06T10:00:00+00:00",
  expires_at: "2027-01-04T10:00:00+00:00",
};

describe("MemoryReceiptStore (web fallback: memory only)", () => {
  it("keeps slots per owner and never persists", async () => {
    const store = new MemoryReceiptStore();
    await store.write("owner-a", receipt);
    expect((await store.read("owner-a"))?.capability).toBe(receipt.capability);
    expect(await store.read("owner-b")).toBeNull();
    await store.clear("owner-a");
    expect(await store.read("owner-a")).toBeNull();
  });
});

function slotBackend(slots: Map<string, string>) {
  return async (cmd: string, args?: unknown) => {
    const owner = String((args as { owner?: string } | undefined)?.owner);
    if (cmd === "receipt_get") return slots.get(owner) ?? null;
    if (cmd === "receipt_set") {
      slots.set(owner, String((args as { payload?: string } | undefined)?.payload));
      return null;
    }
    if (cmd === "receipt_clear") {
      slots.delete(owner);
      return null;
    }
    throw new Error(`unexpected command ${cmd}`);
  };
}

describe("StrongholdReceiptStore", () => {
  it("round-trips through receipt_get/set/clear per owner slot", async () => {
    const slots = new Map<string, string>();
    vi.mocked(invoke).mockImplementation(slotBackend(slots));
    const store = new StrongholdReceiptStore();
    await store.write("owner-a", receipt);
    expect((await store.read("owner-a"))?.receipt_id).toBe(receipt.receipt_id);
    expect(await store.read("owner-b")).toBeNull();
    await store.clear("owner-a");
    expect(await store.read("owner-a")).toBeNull();
  });

  it("treats a corrupt payload as no receipt and clears the slot", async () => {
    const slots = new Map<string, string>([["owner-a", "not-json"]]);
    vi.mocked(invoke).mockImplementation(slotBackend(slots));
    const store = new StrongholdReceiptStore();
    expect(await store.read("owner-a")).toBeNull();
    expect(slots.has("owner-a")).toBe(false);
  });
});
