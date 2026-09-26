import { invoke } from "@tauri-apps/api/core";
import type { CampusAuthGateway, LoginInput, SessionStatus, Verify2FAInput } from "./types";

interface AuthReply {
  state: SessionStatus["state"];
  username?: string;
  methods?: string[];
  message?: string;
}

export class TauriCampusAuthGateway implements CampusAuthGateway {
  async restore(): Promise<SessionStatus> {
    return this.call("campus_restore");
  }

  async login(input: LoginInput): Promise<SessionStatus> {
    // 密码只作为本次 invoke 参数传递，Rust command 不落日志、不写普通文件。
    return this.call("campus_login", { input });
  }

  async verify2fa(input: Verify2FAInput): Promise<SessionStatus> {
    return this.call("campus_verify_2fa", { input });
  }

  async logout(): Promise<void> {
    await invoke("campus_logout");
  }

  private normalize(reply: AuthReply): SessionStatus {
    if (reply.state === "ready") return { state: "ready", username: reply.username ?? "" };
    if (reply.state === "need-2fa") {
      return { state: "need-2fa", username: reply.username ?? "", methods: reply.methods ?? [] };
    }
    if (reply.state === "error") {
      return { state: "error", username: reply.username ?? null, message: reply.message ?? "校园登录失败" };
    }
    return { state: "idle", username: null };
  }

  private async call(command: string, args?: Record<string, unknown>): Promise<SessionStatus> {
    try {
      return this.normalize(await invoke<AuthReply>(command, args));
    } catch (error) {
      return {
        state: "error",
        username: null,
        message: error instanceof Error ? error.message : "Tauri 校园认证命令不可用",
      };
    }
  }
}
