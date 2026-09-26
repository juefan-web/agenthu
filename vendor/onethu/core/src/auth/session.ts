/**
 * CampusSession —— OneTHU 会话持有者（lib 单管线版，2026-09-16 P4 坍缩）。
 *
 * 登录链已统一到 thu-info-lib（apps/desktop 的 infoLib.ts：SM2 + 2FA hooks +
 * roam-id），本类不再承载登录状态机——它只剩三件事：
 *  ① 持有共享 HttpClient 与 learn/info 客户端（会话事实源 = 共享 CookieJar）；
 *  ② 暴露凭据给选课 id-bounce 重登（xkCredentials）与电子身份窗口（getIdCredentials）；
 *  ③ 承载轻量登录态标记（state/username/finger3），供 UI 层展示与持久层读写。
 *
 * 退役记录：demoLogin 全链（login/send2FA/verify2FA/relearnRoam）、era 快照
 * 体系（#seedJar/#infoEraCookies/#learnEraCookies/#cardEraCookies）、softRelogin/
 * keepalive（→ apps/desktop libSoftRelogin/libEnsureSession，指数冷却在调用方）。
 * 会话自愈统一走 lib verifyAndReLogin 语义：auth-dance 重放钩子 + InfoClient
 * renewers + 10min keepalive 探针全部接到同一入口。
 */
import { makeFingerprint } from "./store.js";
import type { FetchLike } from "../http.js";
import type { LearnClient } from "../learn/client.js";
import type { InfoClient } from "../info/client.js";

export type SessionState = "idle" | "need-2fa" | "ready";

export interface CampusSessionOptions {
  http: HttpClient;
  learn: LearnClient;
  info: InfoClient;
  fetchLike: FetchLike;
  fingerprint?: string;
}

import type { HttpClient } from "../http.js";

export class CampusSession {
  readonly http: HttpClient;
  readonly learn: LearnClient;
  readonly info: InfoClient;
  readonly fetchLike: FetchLike;
  fingerprint: string;

  state: SessionState = "idle";
  username = "";
  /** 仅内存保存，logout 即清；选课 id-bounce 与 dorm/library 直登需要 */
  #password = "";
  /** 受信凭据（lib 链 SAVE_FINGER 响应 = fingerGenPrint），持久化后下次登录免 2FA */
  finger3 = "";

  constructor(options: CampusSessionOptions) {
    this.http = options.http;
    this.learn = options.learn;
    this.info = options.info;
    this.fetchLike = options.fetchLike;
    this.fingerprint = options.fingerprint ?? makeFingerprint();
    // dorm/library 按 lib roam("id") 账密直登 id 需要原始凭据（仅内部数据层使用，勿外传；
    // 重启恢复等无密码场景返回空串，InfoClient 自动回退 SSO 发票路径）
    this.info.setIdCredentials(() => ({
      username: this.username,
      password: this.#password,
      fingerprint: this.fingerprint,
      // checkSingle 确认页的 fingerGenPrint（SAVE_FINGER 受信凭据；重启恢复等无密码
      // 场景 finger3 可能仍在——确认页路径照常可用）
      finger3: this.finger3 || undefined,
    }));
    // InfoClient 会话过期续约由 app 层 setRenewers 接到 lib 会话守卫（libEnsureSession）
  }

  /** 电子身份窗口自动填入用凭据（仅内存有密码时可用；重启恢复场景返回 null——
   *  调用方据此降级为手动输入）。仅本机窗口初始化脚本使用，绝不落盘。 */
  getIdCredentials(): { username: string; password: string } | null {
    if (!this.username || !this.#password) return null;
    return { username: this.username, password: this.#password };
  }

  /** 选课系统 id-bounce 重登需要原始凭据（仅内部数据层使用，勿外传） */
  get xkCredentials(): { username: string; password: string; fingerprint: string } {
    return { username: this.username, password: this.#password, fingerprint: this.fingerprint };
  }

  /** 桌面端「记住密码」注入（仅内存，不落盘到 core）：重启恢复的 cookie 会话过期后，
   *  dorm-library 的 id 账密直登（#idCredentials）与选课重登需要原始凭据。 */
  injectCredentials(username: string, password: string): void {
    if (username) this.username = username;
    this.#password = password;
  }

  /** 重置内存会话（logout 用；finger3 属设备信任，保留在 store） */
  reset(): void {
    this.#password = "";
    this.state = "idle";
    this.http.jar.clear();
  }
}
