import { describe, expect, it, vi } from "vitest";
import { BackendClient, BackendHttpError } from "./client";
import { canonicalJson, deletionRequestDigest, fetchReceiptWithCapability } from "./data";

// 冻结样本逐字镜像自 tests/fixtures/deletion-recover-digest.json
// （D-036 §8-2：双端必须对这些 body 产出逐字节相同的摘要）。
const PINNED = [
  {
    body: {
      preview_id: "c47ac1b7-4d5a-4b8e-8f2a-3d1c9e7b5a11",
      preview_digest: "a".repeat(64),
      client_request_id: "recover-sample-0001",
      confirmed: true,
    },
    canonical:
      '{"client_request_id":"recover-sample-0001","confirmed":true,"preview_digest":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","preview_id":"c47ac1b7-4d5a-4b8e-8f2a-3d1c9e7b5a11"}',
    sha256: "8a5d8807ce810eb749ca9c9cdd08650a4726440bc2fa373f0380e04e69fd2712",
  },
  {
    body: {
      preview_id: "0f9e8d7c-6b5a-4c3d-2e1f-0a9b8c7d6e5f",
      preview_digest: `0123456789abcdef`.repeat(4),
      client_request_id: "回执-恢复-样本-0002",
      confirmed: true,
    },
    sha256: "4c15c6e8dce18fddd4f84397a120b92ca842d536a971e511e71dd12e12f5ec27",
  },
];

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers });
}

describe("recover digest canonicalization (frozen fixture)", () => {
  it("reproduces the pinned canonical form and digest byte-for-byte", () => {
    expect(canonicalJson(PINNED[0].body)).toBe(PINNED[0].canonical);
    for (const sample of PINNED) {
      expect(deletionRequestDigest(sample.body)).toBe(sample.sha256);
    }
  });

  it("sorts keys recursively and keeps non-ASCII real UTF-8", () => {
    expect(canonicalJson({ b: 1, a: { d: 2, c: 3 } })).toBe('{"a":{"c":3,"d":2},"b":1}');
    expect(canonicalJson({ k: "回执" })).toBe('{"k":"回执"}');
  });
});

describe("fetchReceiptWithCapability", () => {
  const receipt = {
    id: "0b6a6c8e-4a1c-4c2a-9d3e-1234567890ab",
    operation_id: "0b6a6c8e-4a1c-4c2a-9d3e-1234567890cd",
    completed_at: null,
    completion_scope: "controlled_live",
    effects: [],
    outstanding_count: 0,
    backup_expires_at: null,
    provider_limitations: [],
    local_cleanup_required: true,
    audit_receipt_version: "1",
  };

  it("sends the capability as the bearer and parses the receipt", async () => {
    const fetcher = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => jsonResponse(200, receipt));
    const parsed = await fetchReceiptWithCapability("http://backend", "r-1", "cap-token", fetcher);
    expect(parsed?.local_cleanup_required).toBe(true);
    const [url, init] = fetcher.mock.calls[0];
    expect(String(url)).toBe("http://backend/v1/data/receipts/r-1");
    expect((init as RequestInit).headers).toEqual({ Authorization: "Bearer cap-token" });
  });

  it("maps every failure shape to null (no enumeration surface)", async () => {
    for (const status of [401, 404, 410]) {
      const fetcher = vi.fn(async () => jsonResponse(status, { error: { code: "not_found", message: "x" } }));
      expect(await fetchReceiptWithCapability("http://b", "r", "cap", fetcher)).toBeNull();
    }
  });
});

describe("BackendClient /v1/data surface", () => {
  function client(fetcher: typeof fetch): BackendClient {
    return new BackendClient({ baseUrl: "http://backend", fetcher, getToken: () => "jwt" });
  }

  it("posts previews with the raw target and parses the DTO", async () => {
    const preview = {
      id: "c47ac1b7-4d5a-4b8e-8f2a-3d1c9e7b5a11",
      target: {},
      graph_version: "v1",
      data_generation: 1,
      preview_digest: "a".repeat(64),
      expires_at: "2026-10-06T12:00:00+00:00",
      effects: [],
      limitations: [],
    };
    const fetcher = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => jsonResponse(201, preview));
    const parsed = await client(fetcher).createDataPreview({ kind: "account" });
    expect(parsed.id).toBe(preview.id);
    const [url, init] = fetcher.mock.calls[0];
    expect(String(url)).toBe("http://backend/v1/data/previews");
    expect((init as RequestInit).method).toBe("POST");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ kind: "account" });
  });

  it("confirm parses an operation whose always-emitted keys are null", async () => {
    const operation = {
      id: "0b6a6c8e-4a1c-4c2a-9d3e-1234567890ab",
      kind: "DELETION",
      target: null,
      status: "QUEUED",
      phase: null,
      version: 1,
      data_generation: 2,
      created_at: "2026-10-06T10:00:00+00:00",
      updated_at: "2026-10-06T10:00:00+00:00",
      next_retry_at: null,
      expires_at: null,
      progress: { processed: 0, total: 4, outstanding_count: 4 },
      error: null,
      receipt_id: null,
      receipt_capability: "one-time-capability",
    };
    const fetcher = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => jsonResponse(202, operation));
    const parsed = await client(fetcher).confirmDataDeletion({
      preview_id: "c47ac1b7-4d5a-4b8e-8f2a-3d1c9e7b5a11",
      preview_digest: "a".repeat(64),
      client_request_id: "confirm-key-0001",
      confirmed: true,
    });
    expect(parsed.receipt_capability).toBe("one-time-capability");
  });

  it("carries the error envelope code on BackendHttpError", async () => {
    const fetcher = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) =>
      jsonResponse(409, { error: { code: "generation_stale", message: "moved" } }),
    );
    const error = await client(fetcher).getDataOperation("0b6a6c8e-4a1c-4c2a-9d3e-1234567890ab").catch((e) => e);
    expect(error).toBeInstanceOf(BackendHttpError);
    expect((error as BackendHttpError).code).toBe("generation_stale");
  });

  it("pushEventsTracked sends and captures X-Data-Generation", async () => {
    const batch = { accepted_event_ids: ["e-1"], duplicate_event_ids: [], rejected: [], next_cursor: null };
    const fetcher = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => jsonResponse(200, batch, { "X-Data-Generation": "7" }));
    const envelope = {
      client_event_id: "e-1",
      type: "study.course.discovered",
      occurred_at: "2026-09-26T10:00:00+08:00",
      source: "onethu",
      data: { course_id: "c-1" },
      context: {},
      provenance: {
        connector: "onethu",
        connector_version: "1",
        upstream_id: "course:c-1",
        semantic_version: "v1",
        fetched_at: "2026-09-26T10:00:00+08:00",
      },
    };
    const result = await client(fetcher).pushEventsTracked(
      { events: [envelope], client_cursor: null },
      6,
    );
    expect(result.generation).toBe(7);
    const init = fetcher.mock.calls[0][1] as RequestInit;
    expect(new Headers(init.headers).get("X-Data-Generation")).toBe("6");
    // 兼容窗：不传代际 → 不发头
    const fetcher2 = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => jsonResponse(200, batch, { "X-Data-Generation": "1" }));
    await client(fetcher2).pushEventsTracked({ events: [envelope], client_cursor: null });
    const init2 = fetcher2.mock.calls[0][1] as RequestInit;
    expect(new Headers(init2.headers).get("X-Data-Generation")).toBeNull();
  });
});
