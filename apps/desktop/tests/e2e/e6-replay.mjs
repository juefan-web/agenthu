#!/usr/bin/env node
// E6 recorded-replay provider（OpenAI wire-format，零依赖，M4 出口 e2e 用）。
// 与 e5-replay.mjs 同口径的 embeddings/文本应答，另加两个模式（默认
// "grounding" 与 E5 行为一致）：
//  - "chat-tools"：/v1/responses 首轮（input 为字符串且带 tools）回
//    function_call（task.create 提案，参数固定）；续轮（input 为
//    function_call/function_call_output 数组）回纯文本收尾——场景 2 的
//    L2 pending action 链。
//  - "unavailable"：/v1/responses 一律 503——场景 5 的断供面（runner 侧
//    明确失败，计划/重排走确定性路径不受影响）。
// 模式经 POST /__mode {"mode":"chat-tools"} 切换（spec 内 fetch 控制，
//    免重启）；GET /__mode 回读。不转发任何真实供应商；store=False 钉死
//    不受影响。
import http from "node:http";

const PORT = Number(process.env.E6_REPLAY_PORT ?? 9099);
const DIM = 1536;
const MEMORY_HEADER = "已确认的个人学习记忆";
const MEMORY_ABSENT = "（本次回答没有参考任何学习记忆。）";

let mode = "grounding";

const TASK_CREATE_ARGS = JSON.stringify({
  title: "复习第三章（E6 建议）",
  estimated_duration_minutes: 45,
});

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
    request.on("end", () => resolve(Buffer.concat(chunks).toString("utf-8")));
    request.on("error", reject);
  });
}

function sendJson(response, status, payload) {
  const body = JSON.stringify(payload);
  response.writeHead(status, { "content-type": "application/json", "content-length": Buffer.byteLength(body) });
  response.end(body);
}

function buildAnswer(input) {
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

function responsesPayload(body, overrides = {}) {
  return {
    id: "resp_e6_replay",
    object: "response",
    created_at: Math.floor(Date.now() / 1000),
    model: body.model,
    status: "completed",
    output: [],
    usage: { input_tokens: 10, output_tokens: 5 },
    ...overrides,
  };
}

const server = http.createServer(async (request, response) => {
  const url = request.url ?? "";
  try {
    if (request.method === "POST" && url === "/__mode") {
      const body = JSON.parse(await readBody(request));
      if (!["grounding", "chat-tools", "unavailable"].includes(body.mode)) {
        sendJson(response, 400, { error: { message: `unknown mode ${body.mode}` } });
        return;
      }
      mode = body.mode;
      console.log(`[e6-replay] mode -> ${mode}`);
      sendJson(response, 200, { mode });
      return;
    }
    if (request.method === "GET" && url === "/__mode") {
      sendJson(response, 200, { mode });
      return;
    }
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
      if (mode === "unavailable") {
        console.log("[e6-replay] responses -> 503 (unavailable mode)");
        sendJson(response, 503, { error: { message: "e6-replay: provider unavailable (scripted)" } });
        return;
      }
      if (mode === "chat-tools") {
        const isFollowUp = Array.isArray(body.input);
        if (!isFollowUp) {
          console.log(`[e6-replay] responses chat-tools first turn (tools=${(body.tools ?? []).length})`);
          sendJson(response, 200, responsesPayload(body, {
            output: [{
              id: "fc_e6_1",
              type: "function_call",
              call_id: "call-e6-1",
              name: "task.create",
              arguments: TASK_CREATE_ARGS,
            }],
          }));
          return;
        }
        console.log("[e6-replay] responses chat-tools follow-up turn -> text");
        sendJson(response, 200, responsesPayload(body, {
          output: [{
            id: "msg_e6_final",
            type: "message",
            role: "assistant",
            status: "completed",
            content: [{ type: "output_text", text: "已为你创建待确认任务，请在「确认」里查看。", annotations: [] }],
          }],
        }));
        return;
      }
      const input = typeof body.input === "string" ? body.input : "";
      const text = buildAnswer(input);
      console.log(`[e6-replay] responses grounding model=${body.model} store=${body.store}`);
      sendJson(response, 200, responsesPayload(body, {
        output: [{
          id: "msg_e6",
          type: "message",
          role: "assistant",
          status: "completed",
          content: [{ type: "output_text", text, annotations: [] }],
        }],
      }));
      return;
    }
    sendJson(response, 404, { error: { message: `e6-replay: no route ${request.method} ${url}` } });
  } catch (error) {
    console.error(`[e6-replay] ${request.method} ${url} failed:`, error);
    sendJson(response, 500, { error: { message: String(error) } });
  }
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`[e6-replay] listening on http://127.0.0.1:${PORT} (mode=${mode}; POST /__mode to switch: grounding | chat-tools | unavailable)`);
});
