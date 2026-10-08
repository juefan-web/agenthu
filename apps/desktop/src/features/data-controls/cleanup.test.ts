import { beforeEach, describe, expect, it, vi } from "vitest";
import { LocalEventQueue } from "../../sync/queue";
import { queueCorruptKey, queueKey } from "../../sync/owner";
import { dataGenerationKey } from "../../sync/generation";
import {
  type LocalCleanupDeps,
  cleanupStateText,
  readCleanupRecord,
  runCleanupChecks,
  runLocalCleanup,
  writeCleanupRecord,
  cleanupStorageKey,
} from "./cleanup";

function makeDeps(overrides: Partial<LocalCleanupDeps> = {}): LocalCleanupDeps & { log: string[] } {
  const log: string[] = [];
  return {
    log,
    clearQueueData: async (ownerKey) => {
      log.push(`clear:${ownerKey}`);
      return 4;
    },
    countQueueData: async () => 0,
    clearDraft: async () => {
      log.push("draft-cleared");
    },
    draftPresent: async () => false,
    logoutSession: async () => {
      log.push("logged-out");
    },
    tokenPresent: async () => false,
    storage: null,
    ...overrides,
  };
}

describe("本机清理状态机（B 稿 §3）", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("顺序：登出 → 队列清除 → 草稿清除 → 代际清除 → 检查 → verified", async () => {
    const deps = makeDeps();
    const record = await runLocalCleanup(deps, "owner-key-0001");
    expect(record.state).toBe("verified");
    expect(deps.log).toEqual(["logged-out", "clear:owner-key-0001", "draft-cleared"]);
    // 回执槽是信息行：恒 ok、文案声明独立保留
    const receiptRow = record.checks?.find((check) => check.name === "回执槽");
    expect(receiptRow?.ok).toBe(true);
    expect(receiptRow?.detail).toContain("独立保留");
  });

  it("检查未全过 → failed；重试可修复", async () => {
    let draftLeft = true;
    const deps = makeDeps({ draftPresent: async () => draftLeft });
    const failed = await runLocalCleanup(deps, "owner-key-0001");
    expect(failed.state).toBe("failed");
    expect(failed.checks?.find((check) => check.name === "Focus 草稿")?.ok).toBe(false);

    draftLeft = false;
    const retried = await runLocalCleanup(deps, "owner-key-0001");
    expect(retried.state).toBe("verified");
  });

  it("清理动作抛错 → failed 带原因，不伪造 verified", async () => {
    const deps = makeDeps({ clearQueueData: async () => { throw new Error("sqlite locked"); } });
    const record = await runLocalCleanup(deps, "owner-key-0001");
    expect(record.state).toBe("failed");
    expect(record.error).toContain("sqlite locked");
  });

  it("verified = 可复跑检查输出：键存在性/行数/代际（localStorage 面）", async () => {
    localStorage.setItem(queueKey("owner-key-0001"), JSON.stringify({ events: [], cursor: null }));
    localStorage.setItem(dataGenerationKey("owner-key-0001"), "3");
    const deps = makeDeps({ storage: localStorage, draftPresent: async () => localStorage.getItem("agenthu.focus-draft:owner-key-0001") !== null });
    const before = await runCleanupChecks(deps, "owner-key-0001");
    expect(before.find((check) => check.name === "队列存储键")?.ok).toBe(false);
    expect(before.find((check) => check.name === "数据代际标记")?.ok).toBe(false);

    localStorage.removeItem(queueKey("owner-key-0001"));
    localStorage.removeItem(dataGenerationKey("owner-key-0001"));
    const after = await runCleanupChecks(deps, "owner-key-0001");
    expect(after.every((check) => check.ok)).toBe(true);
  });

  it("记录读写往返 + 状态文案", () => {
    writeCleanupRecord(localStorage, "owner-key-0001", { state: "verified", checks: [], updated_at: "2026-10-07T10:00:00+08:00" });
    expect(readCleanupRecord(localStorage, "owner-key-0001")?.state).toBe("verified");
    expect(localStorage.getItem(cleanupStorageKey("owner-key-0001"))).toBeTruthy();
    expect(readCleanupRecord(localStorage, "other-owner-0002")).toBeNull();
    expect(cleanupStateText("cleaning")).toBe("正在清理本机数据");
  });
});

describe("LocalEventQueue 本机清理面（owner 显式入参）", () => {
  it("clearOwnerData 清键含损坏隔离备份；countOwnerData 读行数；他 owner 不受影响", async () => {
    const queue = new LocalEventQueue({ storage: localStorage, resolveOwner: () => null });
    const queueA = new LocalEventQueue({ storage: localStorage, resolveOwner: () => "owner-key-0001" });
    const queueB = new LocalEventQueue({ storage: localStorage, resolveOwner: () => "owner-key-0002" });
    const envelope = {
      client_event_id: "evt-1",
      type: "study.note.added",
      occurred_at: "2026-10-07T10:00:00+08:00",
      source: "manual",
      data: {},
      context: {},
      provenance: { connector: "manual", connector_version: "1", upstream_id: "u1", semantic_version: "1", fetched_at: "2026-10-07T10:00:01+08:00" },
    };
    await queueA.add([envelope]);
    await queueB.add([envelope]);
    localStorage.setItem(queueCorruptKey("owner-key-0001"), "{}");

    expect(await queueA.countOwnerData("owner-key-0001")).toBe(1);
    const removed = await queue.clearOwnerData("owner-key-0001", true);
    expect(removed).toBe(1);
    expect(await queue.countOwnerData("owner-key-0001")).toBe(0);
    expect(localStorage.getItem(queueKey("owner-key-0001"))).toBeNull();
    expect(localStorage.getItem(queueCorruptKey("owner-key-0001"))).toBeNull();
    // 另一账号原地保留
    expect(await queue.countOwnerData("owner-key-0002")).toBe(1);
  });
});
