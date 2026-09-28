import { describe, expect, it } from "vitest";
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
});
