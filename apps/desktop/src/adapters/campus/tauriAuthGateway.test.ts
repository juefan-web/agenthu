import { describe, expect, it, vi } from "vitest";
import type { InfoHelper } from "@onethu/info-lib";
import { TauriCampusAuthGateway, type AuthDependencies } from "./tauriAuthGateway";

function dependencies(run: AuthDependencies["run"], overrides: Partial<AuthDependencies> = {}): AuthDependencies {
  return {
    run,
    probe: async () => true,
    restore: async () => null,
    save: async () => undefined,
    clear: async () => undefined,
    ...overrides,
  };
}

describe("TauriCampusAuthGateway", () => {
  it("pauses for method selection and verification code without exposing credentials", async () => {
    let saved: unknown;
    const gateway = new TauriCampusAuthGateway(dependencies(async (helper: InfoHelper) => {
      const method = await helper.twoFactorMethodHook?.(false, "", true);
      expect(method).toBe("totp");
      const code = await helper.twoFactorAuthHook?.();
      expect(code).toBe("123456");
      expect(await helper.trustFingerprintHook?.()).toBe(true);
    }, { save: async (metadata) => { saved = metadata; } }));

    await expect(gateway.login({ username: "12345678", password: "secret" }))
      .resolves.toEqual({ state: "need-2fa", username: "12345678", methods: ["totp"], codeSent: false, selectedMethod: undefined });
    await expect(gateway.send2fa("totp"))
      .resolves.toEqual({ state: "need-2fa", username: "12345678", methods: ["totp"], codeSent: true, selectedMethod: "totp" });
    await expect(gateway.verify2fa({ method: "totp", code: "123456", trustDevice: true }))
      .resolves.toEqual({ state: "ready", username: "12345678" });
    expect(saved).toEqual({ username: "12345678", fingerprint: expect.any(String), finger3: "" });
    // 内存凭据供 learn 静默重登（路径二）使用；登出后必须不可用。
    expect(gateway.silentReloginCredentials()?.username).toBe("12345678");
    await gateway.logout();
    expect(gateway.silentReloginCredentials()).toBeNull();
  });

  it("cancels a pending two-factor login and clears persisted state", async () => {
    let cleared = 0;
    const gateway = new TauriCampusAuthGateway(dependencies(async (helper) => {
      await helper.twoFactorMethodHook?.(true, "", false);
    }, { clear: async () => { cleared += 1; } }));

    await gateway.login({ username: "12345678", password: "secret" });
    await gateway.logout();
    expect(cleared).toBeGreaterThan(0);
  });

  it("drops an invalid restored session after probing it once", async () => {
    let cleared = 0;
    const gateway = new TauriCampusAuthGateway(dependencies(async () => undefined, {
      restore: async () => ({ username: "12345678", fingerprint: "finger", finger3: "" }),
      probe: async () => false,
      clear: async () => { cleared += 1; },
    }));

    await expect(gateway.restore()).resolves.toEqual({
      state: "error",
      username: null,
      message: "校园会话已失效，请重新登录",
    });
    expect(cleared).toBe(1);
  });

  it("shares concurrent session restores", async () => {
    let restores = 0;
    let probes = 0;
    const gateway = new TauriCampusAuthGateway(dependencies(async () => undefined, {
      restore: async () => {
        restores += 1;
        await new Promise((resolve) => setTimeout(resolve, 10));
        return { username: "12345678", fingerprint: "finger", finger3: "" };
      },
      probe: async () => {
        probes += 1;
        await new Promise((resolve) => setTimeout(resolve, 10));
        return true;
      },
    }));

    const [first, second] = await Promise.all([gateway.restore(), gateway.restore()]);
    expect(first).toEqual({ state: "ready", username: "12345678" });
    expect(second).toEqual(first);
    expect(restores).toBe(1);
    expect(probes).toBe(1);
  });

  it("announces the second verification round instead of silently restarting method selection", async () => {
    const gateway = new TauriCampusAuthGateway(dependencies(async (helper) => {
      await helper.twoFactorMethodHook?.(false, "", true);
      await helper.twoFactorAuthHook?.();
      // 未受信设备：roam 重放账密触发第二轮验证
      await helper.twoFactorMethodHook?.(false, "", true);
      const code = await helper.twoFactorAuthHook?.();
      expect(code).toBe("999999");
    }));

    await expect(gateway.login({ username: "12345678", password: "secret" }))
      .resolves.toMatchObject({ state: "need-2fa", codeSent: false });
    await expect(gateway.send2fa("totp")).resolves.toMatchObject({ state: "need-2fa", codeSent: true });
    const secondRound = await gateway.verify2fa({ method: "totp", code: "123456", trustDevice: false });
    expect(secondRound).toMatchObject({ state: "need-2fa", codeSent: false, notice: expect.stringContaining("再次验证") });
    await expect(gateway.send2fa("totp")).resolves.toMatchObject({ state: "need-2fa", codeSent: true });
    await expect(gateway.verify2fa({ method: "totp", code: "999999", trustDevice: false }))
      .resolves.toEqual({ state: "ready", username: "12345678" });
  });

  it("surfaces upstream 2FA failures and revives the dead chain for an in-place retry", async () => {
    let attempts = 0;
    const gateway = new TauriCampusAuthGateway(dependencies(async (helper) => {
      await helper.twoFactorMethodHook?.(false, "", true);
      const code = await helper.twoFactorAuthHook?.();
      attempts += 1;
      if (attempts === 1) throw new Error("验证码不正确");
      expect(code).toBe("654321");
    }));

    await expect(gateway.login({ username: "12345678", password: "secret" }))
      .resolves.toMatchObject({ state: "need-2fa" });
    await expect(gateway.send2fa("totp")).resolves.toMatchObject({ state: "need-2fa", codeSent: true });
    // 验证码错误：上游 LoginError 文案必须透出（原实现折叠为统一文案）
    await expect(gateway.verify2fa({ method: "totp", code: "111111", trustDevice: false }))
      .resolves.toEqual({ state: "error", username: null, message: "验证码不正确" });
    // 链已死：原实现原地重发报「请选择当前可用的验证方式」——现在自动重启并应答
    await expect(gateway.send2fa("totp")).resolves.toMatchObject({ state: "need-2fa", codeSent: true });
    await expect(gateway.verify2fa({ method: "totp", code: "654321", trustDevice: false }))
      .resolves.toEqual({ state: "ready", username: "12345678" });
    expect(attempts).toBe(2);
  });

  it("offers an in-place retry from the error state while credentials are held", async () => {
    let attempts = 0;
    const gateway = new TauriCampusAuthGateway(dependencies(async (helper) => {
      await helper.twoFactorMethodHook?.(false, "", true);
      const code = await helper.twoFactorAuthHook?.();
      attempts += 1;
      if (attempts === 1) throw new Error("验证码不正确");
    }));
    await expect(gateway.login({ username: "12345678", password: "secret" }))
      .resolves.toMatchObject({ state: "need-2fa" });
    await expect(gateway.send2fa("totp")).resolves.toMatchObject({ state: "need-2fa", codeSent: true });
    await expect(gateway.verify2fa({ method: "totp", code: "111111", trustDevice: false }))
      .resolves.toMatchObject({ state: "error", message: "验证码不正确" });
    // 错误态原地重试：免重输密码，回到 2FA 表单
    expect(gateway.canRetryTwoFactor()).toBe(true);
    await expect(gateway.retryTwoFactor()).resolves.toMatchObject({ state: "need-2fa", codeSent: false });
    await expect(gateway.send2fa("totp")).resolves.toMatchObject({ state: "need-2fa", codeSent: true });
    await expect(gateway.verify2fa({ method: "totp", code: "654321", trustDevice: false }))
      .resolves.toEqual({ state: "ready", username: "12345678" });
    // logout 后凭据清空：入口关闭
    await gateway.logout();
    expect(gateway.canRetryTwoFactor()).toBe(false);
    await expect(gateway.retryTwoFactor()).resolves.toBe(null);
  });

  it("retry lands ready directly when the restarted chain needs no 2FA", async () => {
    let askedTwoFactor = true;
    const gateway = new TauriCampusAuthGateway(dependencies(async (helper) => {
      if (askedTwoFactor) {
        askedTwoFactor = false;
        await helper.twoFactorMethodHook?.(false, "", true);
        await helper.twoFactorAuthHook?.();
        throw new Error("验证码不正确");
      }
      // 受信设备重启链不再要求 2FA
    }));
    await gateway.login({ username: "12345678", password: "secret" });
    await gateway.send2fa("totp");
    await expect(gateway.verify2fa({ method: "totp", code: "000000", trustDevice: false }))
      .resolves.toMatchObject({ state: "error" });
    await expect(gateway.retryTwoFactor()).resolves.toEqual({ state: "ready", username: "12345678" });
  });

  it("establishes the learn session right after the login chain and tolerates its failure", async () => {
    let roams = 0;
    const ok = new TauriCampusAuthGateway({
      ...dependencies(async () => undefined),
      roamLearn: async () => { roams += 1; },
    });
    await expect(ok.login({ username: "12345678", password: "secret" }))
      .resolves.toEqual({ state: "ready", username: "12345678" });
    expect(roams).toBe(1);

    const failing = new TauriCampusAuthGateway({
      ...dependencies(async () => undefined),
      roamLearn: async () => { throw new Error("learn roam failed"); },
    });
    await expect(failing.login({ username: "12345678", password: "secret" }))
      .resolves.toEqual({ state: "ready", username: "12345678" });
  });

  it("reuses the remembered fingerprint and finger3 to keep the device-trust chain stable", async () => {
    let saved: unknown;
    const gateway = new TauriCampusAuthGateway(dependencies(async () => undefined, {
      restore: async () => ({ username: "12345678", fingerprint: "device-fingerprint", finger3: "trusted-finger3" }),
      probe: async () => true,
      save: async (metadata) => { saved = metadata; },
    }));
    await gateway.restore();
    await expect(gateway.login({ username: "12345678", password: "secret" }))
      .resolves.toEqual({ state: "ready", username: "12345678" });
    expect(saved).toEqual({ username: "12345678", fingerprint: "device-fingerprint", finger3: "trusted-finger3" });
    expect(gateway.silentReloginCredentials()).toMatchObject({ fingerprint: "device-fingerprint", finger3: "trusted-finger3" });
  });

  it("expires an idle two-factor round and requires a fresh login afterwards", async () => {
    vi.useFakeTimers();
    try {
      const gateway = new TauriCampusAuthGateway(dependencies(async (helper) => {
        await helper.twoFactorMethodHook?.(false, "", true);
        await helper.twoFactorAuthHook?.();
      }));
      const status = await gateway.login({ username: "12345678", password: "secret" });
      expect(status).toMatchObject({ state: "need-2fa" });
      await vi.advanceTimersByTimeAsync(180_000);
      // 超时清链清凭据：原地重试不可用，必须重新登录
      await expect(gateway.send2fa("totp")).rejects.toThrow("登录会话已结束");
    } finally {
      vi.useRealTimers();
    }
  });
});
