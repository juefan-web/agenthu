import { invoke } from "@tauri-apps/api/core";
import { z } from "zod";
import { login, roam, getCsrfToken, type InfoHelper } from "@onethu/info-lib";
import { setPlatformFetch, uFetch } from "@onethu/info-lib/network";
import { webvpnWrap } from "@onethu/core";
import { tauriFetch, isTauriRuntime } from "./tauriTransport";
import type { CampusAuthGateway, LoginInput, SessionStatus, Verify2FAInput } from "./types";

const metadataSchema = z.object({ username: z.string().min(1), fingerprint: z.string().min(1), finger3: z.string() }).strict();
export type SessionMetadata = z.infer<typeof metadataSchema>;
type Method = "wechat" | "mobile" | "totp";
const cancelled = new Error("Campus authentication cancelled");

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

export interface AuthDependencies {
  run(helper: InfoHelper): Promise<void>;
  probe(username: string): Promise<boolean>;
  restore(): Promise<unknown>;
  save(metadata: SessionMetadata): Promise<void>;
  clear(): Promise<void>;
}

export class TauriCampusAuthGateway implements CampusAuthGateway {
  private helper: InfoHelper;
  private completion: Promise<SessionStatus> | undefined;
  private signal = deferred<SessionStatus>();
  private methodGate: ReturnType<typeof deferred<Method>> | undefined;
  private codeGate: ReturnType<typeof deferred<string>> | undefined;
  private methods: Method[] = [];
  private selectedMethod: Method | undefined;
  private trust = false;
  private aborted = false;
  private timeout: ReturnType<typeof setTimeout> | undefined;

  constructor(private readonly deps: AuthDependencies) {
    this.helper = {
      userId: "", password: "", fingerprint: crypto.randomUUID(), fingerGenPrint: "",
      mocked: () => false, clearCookieHandler: async () => undefined,
      trustFingerprintNameHook: async () => "Agenthu",
      trustFingerprintHook: async () => this.trust,
      twoFactorMethodHook: async (wechat, phone, totp) => {
        if (this.aborted) throw cancelled;
        this.methods = [...(wechat ? ["wechat" as const] : []), ...(phone ? ["mobile" as const] : []), ...(totp ? ["totp" as const] : [])];
        if (!this.methods.length) throw new Error("No supported 2FA method");
        this.selectedMethod = undefined;
        this.methodGate = deferred<Method>();
        this.signal.resolve(this.twoFactorStatus(false));
        return this.methodGate.promise;
      },
      twoFactorAuthHook: async () => {
        if (this.aborted) throw cancelled;
        this.codeGate = deferred<string>();
        this.signal.resolve(this.twoFactorStatus(true));
        return this.codeGate.promise;
      },
    };
  }

  isAborted(): boolean { return this.aborted; }

  private twoFactorStatus(codeSent: boolean): SessionStatus {
    return { state: "need-2fa", username: this.helper.userId, methods: this.methods, codeSent, selectedMethod: this.selectedMethod };
  }

  async restore(): Promise<SessionStatus> {
    if (this.completion) return this.twoFactorStatus(!!this.codeGate);
    try {
      this.aborted = false;
      const raw = await this.deps.restore();
      if (raw === null) return { state: "idle", username: null };
      const metadata = metadataSchema.parse(raw);
      if (!await this.deps.probe(metadata.username)) {
        await this.deps.clear();
        return { state: "error", username: null, message: "校园会话已失效，请重新登录" };
      }
      this.helper.userId = metadata.username;
      this.helper.fingerprint = metadata.fingerprint;
      this.helper.fingerGenPrint = metadata.finger3;
      return { state: "ready", username: metadata.username };
    } catch {
      // Offline restores retain the encrypted snapshot for a later attempt.
      return { state: "error", username: null, message: "会话恢复失败，请检查网络或重新登录" };
    }
  }

  async login(input: LoginInput): Promise<SessionStatus> {
    await this.logout();
    if (!/^\d+$/.test(input.username.trim()) || !input.password) {
      return { state: "error", username: null, message: "请输入学号和密码" };
    }
    this.aborted = false;
    this.trust = false;
    this.helper.userId = input.username.trim();
    this.helper.password = input.password;
    this.helper.fingerprint = crypto.randomUUID();
    this.signal = deferred<SessionStatus>();
    this.timeout = setTimeout(() => { void this.logout().catch(() => undefined); }, 180_000);
    this.completion = this.deps.run(this.helper).then(async (): Promise<SessionStatus> => {
      if (this.aborted) throw cancelled;
      if (!await this.deps.probe(this.helper.userId)) throw new Error("Session identity mismatch");
      if (this.aborted) throw cancelled;
      await this.deps.save({ username: this.helper.userId, fingerprint: this.helper.fingerprint, finger3: this.helper.fingerGenPrint });
      return { state: "ready", username: this.helper.userId };
    }).catch(async (): Promise<SessionStatus> => {
      await this.deps.clear().catch(() => undefined);
      return { state: "error", username: null, message: this.aborted ? "登录已取消或超时" : "校园认证失败，请检查账号、密码、验证码或网络后重试" };
    }).finally(() => {
      clearTimeout(this.timeout);
      this.helper.password = "";
      this.methodGate = undefined;
      this.codeGate = undefined;
      this.completion = undefined;
    });
    return Promise.race([this.completion, this.signal.promise]);
  }

  async send2fa(method: string): Promise<SessionStatus> {
    if (!this.methodGate || !this.completion || !this.methods.includes(method as Method)) {
      throw new Error("请选择当前可用的验证方式，或取消后重新登录");
    }
    this.signal = deferred<SessionStatus>();
    this.selectedMethod = method as Method;
    const gate = this.methodGate;
    this.methodGate = undefined;
    gate.resolve(this.selectedMethod);
    return Promise.race([this.completion, this.signal.promise]);
  }

  async verify2fa(input: Verify2FAInput): Promise<SessionStatus> {
    if (!this.codeGate || !this.completion || input.method !== this.selectedMethod || !input.code.trim()) {
      throw new Error("请先选择验证方式并获取验证码");
    }
    this.trust = input.trustDevice;
    this.signal = deferred<SessionStatus>();
    const gate = this.codeGate;
    this.codeGate = undefined;
    gate.resolve(input.code.trim());
    return Promise.race([this.completion, this.signal.promise]);
  }

  async logout(): Promise<void> {
    this.aborted = true;
    clearTimeout(this.timeout);
    this.methodGate?.reject(cancelled);
    this.codeGate?.reject(cancelled);
    await this.completion;
    this.helper.password = "";
    this.helper.userId = "";
    this.helper.fingerGenPrint = "";
    await this.deps.clear();
  }
}

export function createTauriAuthGateway(): TauriCampusAuthGateway {
  const gateway = new TauriCampusAuthGateway({
    run: async (helper) => {
      await login(helper, helper.userId, helper.password);
      await roam(helper, "id", "bb5df85216504820be7bba2b0ae1535b/0");
    },
    probe: async (username) => {
      const csrf = await getCsrfToken();
      const raw = await uFetch(webvpnWrap("https://info.tsinghua.edu.cn/b/info/gxfw_fg/common/grjbxx?_csrf=" + encodeURIComponent(csrf)));
      let parsed: unknown;
      try { parsed = JSON.parse(raw); } catch { return false; }
      const result = z.object({ object: z.object({ ryh: z.string() }) }).safeParse(parsed);
      return result.success && result.data.object.ryh === username;
    },
    restore: () => isTauriRuntime() ? invoke("campus_restore") : Promise.resolve(null),
    save: (metadata) => invoke("campus_save_session", { metadata }),
    clear: async () => { if (isTauriRuntime()) await invoke("campus_logout"); },
  });
  setPlatformFetch(async (url, init) => {
    if (gateway.isAborted()) throw cancelled;
    const response = await tauriFetch(url, init);
    if (gateway.isAborted()) throw cancelled;
    return { status: response.status, headers: [...response.headers], text: await response.text(), finalUrl: response.url };
  });
  return gateway;
}
