// Agenthu: auth-only interface; data clients remain in @onethu/core.
export interface InfoHelper {
  userId: string;
  password: string;
  fingerprint: string;
  fingerGenPrint: string;
  mocked(): boolean;
  clearCookieHandler(): Promise<void>;
  loginErrorHook?: (error: unknown) => void;
  twoFactorMethodHook?: (wechat: boolean, phone: string, totp: boolean) => Promise<"wechat" | "mobile" | "totp" | undefined>;
  twoFactorAuthHook?: () => Promise<string | undefined>;
  trustFingerprintHook?: () => Promise<boolean>;
  trustFingerprintNameHook(): Promise<string>;
  twoFactorAuthLimitHook?: () => Promise<void>;
}
export { login, roam, clearOutstandingLogin, getCsrfToken } from "./lib/core";
