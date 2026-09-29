// Build-time guard for the packaged client's Content Security Policy.
// Enforces the review decision from 2026-09-28: no scheme wildcards in
// connect-src and no unsafe-eval/unsafe-inline in script-src. Since B-4
// (backend_request native forwarding), packaged Backend traffic rides the
// Tauri IPC channel, so the production connect-src must NOT list any
// backend origin — the WebView has no direct outlet left to guard.
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
  // B-4: production must not carry any backend origin — that would reopen a
  // WebView-side direct outlet the native allowlist cannot govern. Browser-mode
  // dev keeps its origins in devCsp.
  const backendLeak = connect.filter((token) => token !== "'self'" && !requiredIpc.includes(token));
  if (backendLeak.length) {
    problems.push(`production connect-src must stay at 'self' + IPC only (${backendLeak.join(" ")} found); Backend traffic goes through backend_request (B-4), dev origins belong in devCsp`);
  }
}

if (problems.length) {
  console.error(`CSP guard failed (${problems.length} problem${problems.length > 1 ? "s" : ""}):`);
  for (const problem of problems) console.error(`  - ${problem}`);
  process.exit(1);
}
console.log("CSP guard passed");
