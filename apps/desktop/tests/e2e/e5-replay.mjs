#!/usr/bin/env node
// E5 recorded-replay provider（OpenAI wire-format，零依赖）。
// 契约见 TASKS/m3-e5-exit-scenario.md「replay 契约」节：
//  - /v1/embeddings：内容哈希 → 1536 维确定性向量（无随机、不落盘）。
//  - /v1/responses：从 input（build_context 产物）解析 [1] chunk 块，取
//    开头 ≤60 字符逐字摘录构造 「excerpt」[1]；含记忆块则附记忆参考句，
//    否则附「无记忆参与」句——E5 (c)/(f) 的断言靶。
// 不转发任何真实供应商；后端侧 store=False 钉死不受影响。
import http from "node:http";

const PORT = Number(process.env.E5_REPLAY_PORT ?? 9099);
const DIM = 1536;
const MEMORY_HEADER = "已确认的个人学习记忆";
const MEMORY_ABSENT = "（本次回答没有参考任何学习记忆。）";

function fnv1a(text) {
  let hash = 0x811c9dc5;
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash >>> 0;
}

function embeddingFor(text) {
  const vector = new Array(DIM);
  let seed = fnv1a(text);
  for (let i = 0; i < DIM; i += 1) {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    vector[i] = (seed >>> 8) / 16777216 - 0.5;
  }
  return vector;
}

function readBody(request) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    request.on("data", (chunk) => chunks.push(chunk));
    request.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    request.on("error", reject);
  });
}

function sendJson(response, status, payload) {
  const body = JSON.stringify(payload);
  response.writeHead(status, { "content-type": "application/json", "content-length": Buffer.byteLength(body) });
  response.end(body);
}

function buildAnswer(input) {
  // chunk 块形如 "[1] （filename，第 N 页）\n<content>"，以空行 /
  // 下一块 / 记忆头 / 问题行结束。摘录取 chunk 原文开头切片——与
  // verify_citations 同一字符串的逐字子串，机械校验必然通过。
  const match = /\[1\] （[^）]*）\r?\n([\s\S]*?)(?=\r?\n\r?\n|\[2\] |已确认的个人学习记忆|问题：)/.exec(input);
  const chunkText = match ? match[1] : "";
  const excerpt = chunkText.trim().slice(0, 60);
  let memorySentence = MEMORY_ABSENT;
  const memoryAt = input.indexOf(MEMORY_HEADER);
  if (memoryAt !== -1) {
    const line = /^- (.+)$/m.exec(input.slice(memoryAt));
    if (line) memorySentence = `（参考学习记忆：${line[1].trim().slice(0, 24)}…）`;
  }
  return `采样定理的要求可以从原文直接核对：「${excerpt}」[1] ${memorySentence}`;
}

const server = http.createServer(async (request, response) => {
  const url = request.url ?? "";
  try {
    if (request.method === "POST" && url === "/v1/embeddings") {
      const body = JSON.parse(await readBody(request));
      const input = Array.isArray(body.input) ? body.input : [body.input];
      sendJson(response, 200, {
        object: "list",
        data: input.map((text, index) => ({ object: "embedding", index, embedding: embeddingFor(String(text)) })),
        model: body.model,
        usage: { prompt_tokens: 0, total_tokens: 0 },
      });
      return;
    }
    if (request.method === "POST" && url === "/v1/responses") {
      const body = JSON.parse(await readBody(request));
      const input = typeof body.input === "string" ? body.input : "";
      const text = buildAnswer(input);
      console.log(`[e5-replay] responses model=${body.model} store=${body.store} memories=${input.includes(MEMORY_HEADER)}`);
      sendJson(response, 200, {
        id: "resp_e5_replay",
        object: "response",
        created_at: Math.floor(Date.now() / 1000),
        model: body.model,
        status: "completed",
        output: [{ id: "msg_e5", type: "message", role: "assistant", status: "completed", content: [{ type: "output_text", text, annotations: [] }] }],
      });
      return;
    }
    sendJson(response, 404, { error: { message: `e5-replay: no route ${request.method} ${url}` } });
  } catch (error) {
    console.error(`[e5-replay] ${request.method} ${url} failed:`, error);
    sendJson(response, 500, { error: { message: String(error) } });
  }
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`[e5-replay] listening on http://127.0.0.1:${PORT} (embeddings ${DIM}-dim deterministic, responses chunk-excerpt + memory toggle)`);
});
