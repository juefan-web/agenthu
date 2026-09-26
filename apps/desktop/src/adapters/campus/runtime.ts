import {
  CampusSession,
  HttpClient,
  InfoClient,
  LearnClient,
  MemoryCookieJar,
  webvpnWrap,
} from "@onethu/core";
import { OneThuCampusAdapter } from "./onethuAdapter";
import { TauriCampusAuthGateway } from "./tauriAuthGateway";
import { tauriFetch } from "./tauriTransport";

export function createCampusRuntime() {
  const http = new HttpClient({
    fetch: (url, init) => tauriFetch(url, init),
    jar: new MemoryCookieJar(),
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
  const auth = new TauriCampusAuthGateway();
  return {
    session,
    adapter: new OneThuCampusAdapter({ session, auth }),
  };
}
