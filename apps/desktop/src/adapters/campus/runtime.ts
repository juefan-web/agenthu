import {
  CampusSession,
  HttpClient,
  InfoClient,
  LearnClient,
  webvpnWrap,
} from "@onethu/core";
import { OneThuCampusAdapter } from "./onethuAdapter";
import { createTauriAuthGateway } from "./tauriAuthGateway";
import { tauriFetch } from "./tauriTransport";

export function createCampusRuntime() {
  const http = new HttpClient({
    fetch: (url, init) => tauriFetch(url, init),
    // Cookies stay in Rust; the vendor jar is intentionally inert.
    jar: { getCookies: () => [], setFromResponse() {}, setRaw() {}, serialize: () => "[]", hydrate() {}, clear() {} },
  });
  http.webVPNEncoder = webvpnWrap;
  const learn = new LearnClient(http);
  const info = new InfoClient(http);
  const session = new CampusSession({
    http,
    learn,
    info,
    fetchLike: (url, init) => tauriFetch(url, init),
  });
  const auth = createTauriAuthGateway();
  // Only the adapter crosses this boundary. The raw session (cookies,
  // credential accessors) stays private to the runtime wiring.
  return { adapter: new OneThuCampusAdapter({ session, auth }) };
}
