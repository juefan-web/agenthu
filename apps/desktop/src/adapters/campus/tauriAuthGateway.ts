import { invoke } from "@tauri-apps/api/core";
import { z } from "zod";
import { clearOutstandingLogin, login, roam, getCsrfToken, type InfoHelper } from "@onethu/info-lib";
import { setPlatformFetch, uFetch } from "@onethu/info-lib/network";
import { webvpnWrap } from "@onethu/core";
import { tauriFetch, isTauriRuntime } from "./tauriTransport";
import type { CampusAuthGateway, LoginInput, SessionStatus, Verify2FAInput } from "./types";

const metadataSchema = z.object({ username: z.string().min(1), fingerprint: z.string().min(1), finger3: z.string() }).strict();
export type SessionMetadata = z.infer<typeof metadataSchema>;
type Method = "wechat" | "mobile" | "totp";
/** learn 的 id 表单漫游 payload（上游 OneTHU libRoamLearn 同源）：登录链尾的
 *  roam-id 只覆盖 info，learn 会话必须显式建立，否则采集确定性失败。 */
const LEARN_ROAM_ID_FORM = "bb5df85216504820be7bba2b0ae1535b/0";
/** 单轮 2FA（选方式/输码）的空闲超时；hook 触发或用户动作都会重置计时，
 *  不再用一个总计时覆盖多轮验证 + 用户输码。 */
const ROUND_TIMEOUT_MS = 180_000;
const cancelled = new Error("Campus authentication cancelled");

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

export interface AuthDependencies {
  run(helper: InfoHelper): Promise<void>;
  /** 登录链成功后的 learn 会话建立；失败被容忍（采集时由 resume/凭据链兜底）。 */
  roamLearn?(helper: InfoHelper): Promise<void>;
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
  private methodGateWaiter: ReturnType<typeof deferred<void>> | undefined;
  private codeGateWaiter: ReturnType<typeof deferred<void>> | undefined;
  private methods: Method[] = [];
  private selectedMethod: Method | undefined;
  private trust = false;
  private aborted = false;
  private timedOut = false;
  private timeout: ReturnType<typeof setTimeout> | undefined;
  private restoreInFlight: Promise<SessionStatus> | undefined;
  /** 登录链凭据（仅内存；logout/下次登录清除）：2FA 链自愈重启与 learn 静默
   *  重登的账密源（上游 inflight 同语义）。不落盘、不随会话持久化。 */
  private credentials: { username: string; password: string } | null = null;
  /** 设备身份（Stronghold 元数据回填）：指纹与受信凭据跨登录稳定，信任链才成立。 */
  private remembered = { fingerprint: "", finger3: "" };
  /** 当前链的第几轮 2FA；>=2 时状态携带显式提示（未受信设备的 roam 重放验证）。 */
  private round = 0;
  /** 链纪元：每次 startChain 递增，过期链的收尾逻辑不得触碰新链状态。 */
  private chainEpoch = 0;

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
        this.round += 1;
        this.selectedMethod = undefined;
        this.methodGate = deferred<Method>();
        this.resolveGateWaiter("methodGateWaiter");
        this.armTimeout();
        this.signal.resolve(this.twoFactorStatus(false));
        return this.methodGate.promise;
      },
      twoFactorAuthHook: async () => {
        if (this.aborted) throw cancelled;
        this.codeGate = deferred<string>();
        this.resolveGateWaiter("codeGateWaiter");
        this.armTimeout();
        this.signal.resolve(this.twoFactorStatus(true));
        return this.codeGate.promise;
      },
    };
  }

  isAborted(): boolean { return this.aborted; }

  /** learn 静默重登路径二的账密供应（runtime 接线）。仅内存凭据期间可用；
   *  指纹/受信凭据取自登录链 helper，与 session 内的展示状态无关。 */
  silentReloginCredentials(): { username: string; password: string; fingerprint: string; finger3?: string } | null {
    if (!this.credentials) return null;
    return {
      username: this.credentials.username,
      password: this.credentials.password,
      fingerprint: this.helper.fingerprint,
      finger3: this.helper.fingerGenPrint || undefined,
    };
  }

  private twoFactorStatus(codeSent: boolean): SessionStatus {
    return {
      state: "need-2fa",
      username: this.helper.userId,
      methods: this.methods,
      codeSent,
      selectedMethod: this.selectedMethod,
      // 未受信设备在 roam 重放账密时会再触发一轮验证：必须显式告知，
      // 不得静默回到方式选择页让用户以为登录失败重来。
      notice: this.round >= 2 ? "安全策略要求对本机再次验证，本轮通过后即可完成登录" : undefined,
    };
  }

  private resolveGateWaiter(field: "methodGateWaiter" | "codeGateWaiter"): void {
    const waiter = this[field];
    this[field] = undefined;
    waiter?.resolve();
  }

  /** 等待下一轮 methodGate 就位。hook 可能在注册 waiter 之前就已同步触发
   *  （此时 gate 已存在），必须先查 gate 再挂 waiter，否则永久挂起。 */
  private waitForMethodGate(): Promise<void> {
    if (this.methodGate) return Promise.resolve();
    this.methodGateWaiter ??= deferred<void>();
    return this.methodGateWaiter.promise;
  }

  private waitForCodeGate(): Promise<void> {
    if (this.codeGate) return Promise.resolve();
    this.codeGateWaiter ??= deferred<void>();
    return this.codeGateWaiter.promise;
  }

  private armTimeout(): void {
    clearTimeout(this.timeout);
    this.timeout = setTimeout(() => {
      this.timedOut = true;
      void this.logout().catch(() => undefined);
    }, ROUND_TIMEOUT_MS);
  }

  async restore(): Promise<SessionStatus> {
    if (this.restoreInFlight) return this.restoreInFlight;
    const operation = this.restoreOnce();
    this.restoreInFlight = operation.finally(() => {
      this.restoreInFlight = undefined;
    });
    return operation;
  }

  private async restoreOnce(): Promise<SessionStatus> {
    if (this.completion) return this.twoFactorStatus(!!this.codeGate);
    try {
      this.aborted = false;
      const raw = await this.deps.restore();
      if (raw === null) return { state: "idle", username: null };
      const metadata = metadataSchema.parse(raw);
      // 设备身份在探活前就回填：即使快照失效，下次登录仍复用同一指纹/受信凭据。
      this.remembered = { fingerprint: metadata.fingerprint, finger3: metadata.finger3 };
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
    // info-lib keeps its own process-wide login promise while waiting for 2FA.
    // A cancelled/expired attempt must never poison the next login attempt.
    clearOutstandingLogin();
    if (!/^\d+$/.test(input.username.trim()) || !input.password) {
      return { state: "error", username: null, message: "请输入学号和密码" };
    }
    this.credentials = { username: input.username.trim(), password: input.password };
    this.round = 0;
    this.timedOut = false;
    this.trust = false;
    this.helper.userId = input.username.trim();
    this.helper.password = input.password;
    // 指纹跨登录稳定 + 受信凭据复灌：roam 重放账密时 id 据此放行，
    // 已受信设备不再触发第二轮 2FA（上游 finger3 信任链同语义）。
    this.helper.fingerprint = this.remembered.fingerprint || crypto.randomUUID();
    this.helper.fingerGenPrint = this.remembered.finger3;
    const completion = this.startChain();
    // 登录在 2FA 处暂停交还 UI；signal 由 hook 携带中间状态。
    return Promise.race([completion, this.signal.promise]);
  }

  private startChain(): Promise<SessionStatus> {
    this.aborted = false;
    this.signal = deferred<SessionStatus>();
    this.armTimeout();
    // 链纪元：旧链的 catch/finally 可能晚于自愈重启的新链落账，
    // 过期链不得清掉新链的 gates/completion。
    const epoch = ++this.chainEpoch;
    this.completion = this.deps.run(this.helper).then(async (): Promise<SessionStatus> => {
      if (this.aborted) throw cancelled;
      // learn 会话必须显式建立（D1）。失败被容忍：采集时由 learn.resume 的
      // /f/login SSO 与 credentialProvider 账密链兜底；用户取消则继续透传终止。
      await this.deps.roamLearn?.(this.helper).catch(() => undefined);
      if (this.aborted) throw cancelled;
      if (!await this.deps.probe(this.helper.userId)) throw new Error("登录后的会话身份与账号不一致，请重试");
      if (this.aborted) throw cancelled;
      this.remembered = { fingerprint: this.helper.fingerprint, finger3: this.helper.fingerGenPrint };
      await this.deps.save({ username: this.helper.userId, fingerprint: this.helper.fingerprint, finger3: this.helper.fingerGenPrint });
      return { state: "ready", username: this.helper.userId };
    }).catch(async (error): Promise<SessionStatus> => {
      await this.deps.clear().catch(() => undefined);
      return { state: "error", username: null, message: this.chainErrorMessage(error) };
    }).finally(() => {
      if (this.chainEpoch !== epoch) return;
      clearTimeout(this.timeout);
      this.helper.password = "";
      this.methodGate = undefined;
      this.codeGate = undefined;
      this.completion = undefined;
    });
    return this.completion;
  }

  /** 上游错误原因透出：服务端/上游的中文文案（验证码错误、二次认证上限等）
   *  直接交给 UI；lib 内部英文诊断折叠为通用文案；取消/超时单独成文。 */
  private chainErrorMessage(error: unknown): string {
    if (this.timedOut) return "校园登录已超时（本轮 3 分钟无进展），请重新登录";
    if (error === cancelled) return "登录已取消";
    const message = error instanceof Error ? error.message : "";
    if (message === "Login timeout.") return "校园登录超时（3 分钟），请重试";
    if (message && /[\u4e00-\u9fff]/.test(message)) return message;
    return "校园认证失败，请检查账号、密码、验证码或网络后重试";
  }

  /** 链死自愈（上游 libSend2FA/libVerify2FA 同义）：验证码错误等使整链
   *  settle 后，用内存凭据重启登录链并自动应答方式选择，用户原地重试。
   *  返回重启后的 completion；null 表示无凭据可复活。受信设备重启后可能
   *  直接就绪（不再要求 2FA），调用方以 methodGate 是否存在区分。 */
  private async restartChain(): Promise<{ completion: Promise<SessionStatus> } | null> {
    if (!this.credentials || !this.methods.length) return null;
    this.round = 0;
    this.timedOut = false;
    this.trust = false;
    this.helper.userId = this.credentials.username;
    this.helper.password = this.credentials.password;
    // 指纹与受信凭据保持现值：受信设备重启后免 2FA 直接完成。
    clearOutstandingLogin();
    const completion = this.startChain();
    await Promise.race([
      this.waitForMethodGate(),
      completion.then(() => undefined),
    ]);
    return { completion };
  }

  async send2fa(method: string): Promise<SessionStatus> {
    if (!this.methods.includes(method as Method)) {
      throw new Error("请选择当前可用的验证方式，或取消后重新登录");
    }
    if (!this.completion || !this.methodGate) {
      const revived = await this.restartChain();
      if (!revived) throw new Error("登录会话已结束，请重新登录");
      if (!this.methodGate) return revived.completion;
    }
    this.armTimeout();
    this.signal = deferred<SessionStatus>();
    this.selectedMethod = method as Method;
    const gate = this.methodGate;
    this.methodGate = undefined;
    gate.resolve(this.selectedMethod);
    return Promise.race([this.completion ?? Promise.resolve(this.twoFactorStatus(false)), this.signal.promise]);
  }

  async verify2fa(input: Verify2FAInput): Promise<SessionStatus> {
    if (!input.code.trim()) throw new Error("请先获取并输入验证码");
    if (!this.completion || !this.codeGate) {
      const revived = await this.restartChain();
      if (!revived) throw new Error("登录会话已结束，请重新登录");
      const completion = revived.completion;
      if (this.methodGate) {
        if (!this.methods.includes(input.method as Method)) throw new Error("验证方式已不可用，请重新选择");
        this.signal = deferred<SessionStatus>();
        this.selectedMethod = input.method as Method;
        const gate = this.methodGate;
        this.methodGate = undefined;
        gate.resolve(this.selectedMethod);
        await Promise.race([this.waitForCodeGate(), completion.then(() => undefined)]);
      }
      if (!this.codeGate) return completion;
    }
    if (input.method !== this.selectedMethod) throw new Error("验证方式已切换，请重新获取验证码");
    this.trust = input.trustDevice;
    this.armTimeout();
    this.signal = deferred<SessionStatus>();
    const gate = this.codeGate;
    this.codeGate = undefined;
    gate.resolve(input.code.trim());
    return Promise.race([this.completion ?? Promise.resolve(this.twoFactorStatus(true)), this.signal.promise]);
  }

  async logout(): Promise<void> {
    this.aborted = true;
    this.credentials = null;
    this.round = 0;
    clearOutstandingLogin();
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
      // LearnClient enters through the authenticated WebVPN SSO path on first use;
      // the explicit learn roam runs right after this chain (roamLearn below).
      await login(helper, helper.userId, helper.password);
    },
    roamLearn: async (helper) => {
      // 上游 libRoamLearn 同源：learn 的 id 表单链（表单→check→锚点→包装跟随）。
      // 受信设备（finger3 就绪）免二次认证；未受信触发第二轮验证，
      // 由 gateway 的多轮状态机接住并向用户显式提示。
      await roam(helper, "id", LEARN_ROAM_ID_FORM);
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
