// Build-time guard for the packaged client's Content Security Policy.
// Enforces the review decision from 2026-09-28: no scheme wildcards in
// connect-src, no unsafe-eval/unsafe-inline in script-src, and every
// VITE_BACKEND_URL origin must be explicitly allowlisted in tauri.conf.json.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));

function cspDirectives(csp) {
  return Object.fromEntries(
    csp
      .split(";")
      .map((part) => part.trim())
      .filter(Boolean)
      .map((part) => {
        const [name, ...values] = part.split(/\s+/);
        return [name.toLowerCase(), values];
      }),
  );
}

function backendOrigin(problems) {
  const candidates = [];
  if (process.env.VITE_BACKEND_URL) candidates.push(process.env.VITE_BACKEND_URL);
  for (const name of [".env.local", ".env"]) {
    try {
      const raw = readFileSync(join(root, name), "utf8");
      const line = raw.split(/\r?\n/).find((entry) => entry.startsWith("VITE_BACKEND_URL="));
      if (line) candidates.push(line.slice("VITE_BACKEND_URL=".length).trim().replace(/^["']|["']$/g, ""));
    } catch {
      // No .env file; Vite would fall through to .env.example only via docs.
    }
  }
  const value = candidates.find((entry) => entry && entry.trim() !== "");
  if (!value) return null;
  try {
    return new URL(value).origin;
  } catch {
    problems.push(`VITE_BACKEND_URL is not a valid URL: ${value}`);
    return null;
  }
}

const conf = JSON.parse(readFileSync(join(root, "src-tauri", "tauri.conf.json"), "utf8"));
const csp = conf.app?.security?.csp;
const problems = [];
if (typeof csp !== "string" || csp.trim() === "") {
  problems.push("tauri.conf.json is missing app.security.csp");
}

if (!problems.length) {
  const directives = cspDirectives(csp);
  const connect = directives["connect-src"] ?? [];
  const schemeWildcards = connect.filter((token) => /^(https?|wss?):$|^\*$/.test(token));
  if (schemeWildcards.length) {
    problems.push(`connect-src must not contain scheme wildcards (${schemeWildcards.join(" ")}); allowlist explicit Backend origins instead`);
  }
  const script = directives["script-src"] ?? [];
  const unsafeScript = script.filter((token) => token === "'unsafe-eval'" || token === "'unsafe-inline'" || token === "*");
  if (unsafeScript.length) {
    problems.push(`script-src must not contain wildcards or unsafe-* tokens (${unsafeScript.join(" ")})`);
  }
  // Positive requirement: Tauri v2 IPC origins must be allowlisted, or the
  // packaged WebView falls back to the slow postMessage channel and logs CSP
  // violations ('self' is the app page origin, not the IPC origin).
  const requiredIpc = ["ipc:", "http://ipc.localhost"];
  const missingIpc = requiredIpc.filter((token) => !connect.includes(token));
  if (missingIpc.length) {
    problems.push(`connect-src must include the Tauri IPC origins (${missingIpc.join(" ")}); without them packaged IPC degrades to postMessage`);
  }
  const origin = backendOrigin(problems);
  if (origin && !connect.includes(origin)) {
    problems.push(`VITE_BACKEND_URL origin ${origin} is not allowlisted in app.security.csp connect-src; add it to apps/desktop/src-tauri/tauri.conf.json before building`);
  }
}

if (problems.length) {
  console.error(`CSP guard failed (${problems.length} problem${problems.length > 1 ? "s" : ""}):`);
  for (const problem of problems) console.error(`  - ${problem}`);
  process.exit(1);
}
console.log("CSP guard passed");
