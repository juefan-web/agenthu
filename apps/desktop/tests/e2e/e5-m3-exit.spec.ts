import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { test, expect } from "@playwright/test";

/**
 * E5 — M3 出口场景（后端半边，API 造数）。场景与断言清单见
 * TASKS/m3-e5-exit-scenario.md；栈准备（含 e5-replay.mjs）见
 * tests/e2e/README.md 的 E5 节。
 *
 * UI 半边（#44 讲解页交互）在 #44 合入 main 后追加；B 的上传 UI 落地后
 * 把 (a) 的 API 上传换成 UI 上传即为完整版。
 *
 * 断言编号与任务文件一一对应：(a) 上传/抽取/嵌入 (b) 同意门
 * (c) 记忆参与 (d) 引用可核 (e) 删除记忆 (f) 不再体现 (g) 回答删除。
 */

const backendUrl = process.env.AGENTHU_TEST_BACKEND_URL;
const backendEmail = process.env.AGENTHU_TEST_BACKEND_EMAIL;
const backendPassword = process.env.AGENTHU_TEST_BACKEND_PASSWORD;
test.skip(!backendUrl || !backendEmail || !backendPassword,
  "需要 AGENTHU_TEST_BACKEND_URL / AGENTHU_TEST_BACKEND_EMAIL / AGENTHU_TEST_BACKEND_PASSWORD");
test.skip(process.env.AGENTHU_E5_FULL !== "1",
  "E5 全链需 AGENTHU_E5_FULL=1（compose 栈 + uvicorn + arq worker + e5-replay.mjs，见 tests/e2e/README.md）");

const COURSE = "信号与系统E5";
const RUN = `e5-${Date.now()}`;
// 与 fixtures/make_e5_fixture.py 的 PAGE_TEXTS 逐字一致——(d) 的独立复核基准。
const PAGE_TEXTS = [
  "The sampling theorem requires that the sampling rate must be at least " +
  "twice the highest frequency present in the signal. This lower bound is " +
  "called the Nyquist rate.",
  "Aliasing occurs when the sampling rate falls below the Nyquist rate. " +
  "The folded spectrum overlaps and the original signal cannot be " +
  "recovered exactly.",
];
const QUESTION = "What does the sampling theorem require?";
const MEMORY_CONTENT = "E5 记忆：用户偏好用中文教材对照英文原文理解采样定理";

interface Api {
  get: (path: string) => Promise<unknown>;
  post: (path: string, body?: unknown, method?: string) => Promise<unknown>;
  upload: (path: string, filename: string, contentType: string, bytes: Buffer, fields: Record<string, string>) => Promise<unknown>;
}

async function registerAndLogin(): Promise<Api> {
  // spec 自注册独立账号（E4/§7.6 口径：每跑全新账号，互不残留）
  const email = `${RUN}@e5.test`;
  const register = await fetch(`${backendUrl}/v1/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password: backendPassword, display_name: `E5 ${RUN}` }),
  });
  if (register.status !== 201) throw new Error(`注册失败：HTTP ${register.status} ${(await register.text()).slice(0, 200)}`);
  const login = await fetch(`${backendUrl}/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password: backendPassword }),
  });
  if (!login.ok) throw new Error(`登录失败：HTTP ${login.status}`);
  const token = ((await login.json()) as { access_token: string }).access_token;
  const auth = () => ({ Authorization: `Bearer ${token}` });
  const get = async (path: string) => {
    const res = await fetch(`${backendUrl}${path}`, { headers: auth() });
    if (!res.ok) throw new Error(`GET ${path} → ${res.status}：${(await res.text()).slice(0, 200)}`);
    return res.json();
  };
  const post = async (path: string, body?: unknown, method = "POST") => {
    const res = await fetch(`${backendUrl}${path}`, {
      method,
      headers: { ...auth(), "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`${method} ${path} → ${res.status}：${(await res.text()).slice(0, 300)}`);
    return res.status === 204 ? null : res.json();
  };
  const upload = async (path: string, filename: string, contentType: string, bytes: Buffer, fields: Record<string, string>) => {
    const form = new FormData();
    form.append("file", new Blob([new Uint8Array(bytes)], { type: contentType }), filename);
    for (const [key, value] of Object.entries(fields)) form.append(key, value);
    const res = await fetch(`${backendUrl}${path}`, { method: "POST", headers: auth(), body: form });
    if (!res.ok) throw new Error(`POST ${path} → ${res.status}：${(await res.text()).slice(0, 300)}`);
    return res.json();
  };
  return { get, post, upload };
}

async function waitFor<T>(label: string, probe: () => Promise<T>, done: (value: T) => boolean, timeoutMs = 90_000): Promise<T> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const value = await probe();
    if (done(value)) return value;
    if (Date.now() > deadline) throw new Error(`等待超时：${label}`);
    await new Promise((resolve) => setTimeout(resolve, 1_000));
  }
}

interface ChunkRead {
  page: number | null;
  scan_status: string;
  embedding_present: boolean;
}

test("e5: M3 出口后端半边（上传→同意→提问→引用可核→删记忆→不再体现→删回答）", async () => {
  const api = await registerAndLogin();

  // (a) 上传合成课件，真实 worker 抽取，chunks 全 clean
  const fixture = readFileSync(fileURLToPath(new URL("./fixtures/e5-lecture.pdf", import.meta.url)));
  const file = (await api.upload("/v1/files", "e5-lecture.pdf", "application/pdf", fixture, { course_name: COURSE })) as { id: string };
  const chunks = await waitFor("chunks clean", async () =>
    (await api.get(`/v1/files/${file.id}/chunks?limit=50&offset=0`)) as { items: ChunkRead[] },
    (page) => page.items.length >= 2 && page.items.every((chunk) => chunk.scan_status === "clean"));
  expect(chunks.items.length).toBeGreaterThanOrEqual(2);

  // (b) 同意门：默认关、文案含 ≤30 天监控保留披露、开启回显版本
  const consentBefore = (await api.get(`/v1/grounding-consent?course_name=${encodeURIComponent(COURSE)}`)) as {
    enabled: boolean; consent_text: string; consent_text_version: string;
  };
  expect(consentBefore.enabled).toBe(false);
  expect(consentBefore.consent_text).toContain("30");
  expect(consentBefore.consent_text_version).toBe("v1");
  const consentAfter = (await api.post("/v1/grounding-consent", {
    course_name: COURSE, enabled: true, consent_text_version: consentBefore.consent_text_version,
  }, "PUT")) as { enabled: boolean };
  expect(consentAfter.enabled).toBe(true);

  // 开启触发 backfill：等全部 chunk 嵌入完成（真实队列 → replay embeddings）
  await waitFor("chunks embedded", async () =>
    (await api.get(`/v1/files/${file.id}/chunks?limit=50&offset=0`)) as { items: ChunkRead[] },
    (page) => page.items.length >= 2 && page.items.every((chunk) => chunk.embedding_present));

  // (c) 记忆参与：创建 Learning Memory → 提问 → memory_ids 含它、回答含记忆参考句
  const memory = (await api.post("/v1/memory", {
    content: MEMORY_CONTENT, level: 1, confidence: 0.9, domain: "study",
  })) as { id: string };
  const answer1 = (await api.post("/v1/material/answers", { course_name: COURSE, question: QUESTION })) as {
    id: string; grounded: boolean; answer: string; memory_ids: string[];
    citations: { page: number | null; quote: string }[];
  };

  // (d) 引用可核：grounded、被引页在 fixture 页集合内、quote 是该页原文的
  // 逐字子串（独立复核）。不预设哪页被引——检索排序不属于出口判据
  // （实测 RRF 常把 page-2 chunk 排首，其文本同样回答该问题）。
  expect(answer1.grounded).toBe(true);
  expect(answer1.citations.length).toBe(1);
  expect([1, 2]).toContain(answer1.citations[0]?.page);
  expect(answer1.answer).toContain("」[1]");
  expect((PAGE_TEXTS[(answer1.citations[0]?.page ?? 0) - 1] ?? "?").includes(answer1.citations[0]?.quote ?? "?")).toBe(true);
  expect(answer1.memory_ids).toContain(memory.id);
  expect(answer1.answer).toContain("参考学习记忆：");

  // (e) 删除该 Learning Memory
  await api.post(`/v1/memory/${memory.id}`, undefined, "DELETE");

  // (f) 同一问题再问：不再体现该记忆，引用不受影响
  const answer2 = (await api.post("/v1/material/answers", { course_name: COURSE, question: QUESTION })) as {
    id: string; grounded: boolean; answer: string; memory_ids: string[];
    citations: { page: number | null; quote: string }[];
  };
  expect(answer2.grounded).toBe(true);
  expect(answer2.memory_ids).not.toContain(memory.id);
  expect(answer2.answer).not.toContain("参考学习记忆：");
  expect(answer2.answer).toContain("没有参考任何学习记忆");
  expect(answer2.citations[0]?.page).toBe(answer1.citations[0]?.page);
  expect((PAGE_TEXTS[(answer2.citations[0]?.page ?? 0) - 1] ?? "?").includes(answer2.citations[0]?.quote ?? "?")).toBe(true);

  // (g) 回答删除入口：两条全删，历史清空
  await api.post(`/v1/material/answers/${answer1.id}`, undefined, "DELETE");
  await api.post(`/v1/material/answers/${answer2.id}`, undefined, "DELETE");
  const history = (await api.get(`/v1/material/answers?course_name=${encodeURIComponent(COURSE)}&limit=50&offset=0`)) as { items: unknown[] };
  expect(history.items.length).toBe(0);
});
