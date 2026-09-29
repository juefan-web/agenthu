import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { applySession, CampusConnection } from "./CampusConnection";
import { campus } from "../campus/instance";
import { useSessionStore } from "../state/session";
import type { CampusAdapter } from "../adapters/campus/types";

vi.mock("../campus/instance", () => ({
  campus: {
    restore: vi.fn(),
    login: vi.fn(),
    send2fa: vi.fn(),
    verify2fa: vi.fn(),
    canRetryTwoFactor: vi.fn(() => false),
    retryTwoFactor: vi.fn(),
    logout: vi.fn(),
    getCourses: vi.fn(),
    getAssignments: vi.fn(),
    getSchedule: vi.fn(),
    getAcademicCalendar: vi.fn(),
    collectSnapshot: vi.fn(),
  } satisfies CampusAdapter,
}));
vi.mock("../adapters/campus/tauriTransport", () => ({ isTauriRuntime: () => true }));

const onError = vi.fn();

function renderConnection() {
  return render(<CampusConnection onError={onError} />);
}

beforeEach(() => {
  vi.clearAllMocks();
  onError.mockClear();
  useSessionStore.getState().reset();
  vi.mocked(campus.canRetryTwoFactor).mockReturnValue(false);
});

describe("CampusConnection state machine", () => {
  it("submits credentials and clears the password field immediately", async () => {
    vi.mocked(campus.login).mockResolvedValue({ state: "ready", username: "12345678" });
    renderConnection();
    fireEvent.change(screen.getByLabelText("学号"), { target: { value: "12345678" } });
    const passwordInput = screen.getByLabelText("密码") as HTMLInputElement;
    fireEvent.change(passwordInput, { target: { value: "secret" } });
    fireEvent.submit(screen.getByRole("button", { name: "登录" }).closest("form")!);
    // 密码在请求发出前即从表单 state 清除（登录成功后表单卸载，先持引用断言）
    expect(passwordInput.value).toBe("");
    await waitFor(() => expect(campus.login).toHaveBeenCalledWith({ username: "12345678", password: "secret" }));
  });

  it("offers 2FA method selection and sends the active method", async () => {
    applySession({ state: "need-2fa", username: "12345678", methods: ["totp", "mobile"], codeSent: false });
    vi.mocked(campus.send2fa).mockResolvedValue({ state: "need-2fa", username: "12345678", methods: ["totp", "mobile"], codeSent: true, selectedMethod: "totp" });
    renderConnection();
    fireEvent.click(screen.getByRole("button", { name: "使用验证器" }));
    await waitFor(() => expect(campus.send2fa).toHaveBeenCalledWith("totp"));
  });

  it("announces the second verification round instead of a silent restart", () => {
    applySession({ state: "need-2fa", username: "12345678", methods: ["totp"], codeSent: false, notice: "安全策略要求对本机再次验证，本轮通过后即可完成登录" });
    renderConnection();
    expect(screen.getByRole("status").textContent).toContain("再次验证");
  });

  it("submits the verification code with the selected method and trust flag", async () => {
    applySession({ state: "need-2fa", username: "12345678", methods: ["totp"], codeSent: true, selectedMethod: "totp" });
    vi.mocked(campus.verify2fa).mockResolvedValue({ state: "ready", username: "12345678" });
    renderConnection();
    fireEvent.change(screen.getByLabelText("验证码"), { target: { value: "123456" } });
    fireEvent.click(screen.getByLabelText("信任此设备"));
    fireEvent.submit(screen.getByRole("button", { name: "验证" }).closest("form")!);
    await waitFor(() => expect(campus.verify2fa).toHaveBeenCalledWith({ method: "totp", code: "123456", trustDevice: true }));
  });

  it("surfaces the error message with an explicit role", () => {
    applySession({ state: "error", username: null, message: "验证码不正确" });
    renderConnection();
    expect(screen.getByRole("alert").textContent).toContain("验证码不正确");
  });

  it("offers the in-place retry when credentials are still held", async () => {
    applySession({ state: "error", username: null, message: "验证码不正确" });
    vi.mocked(campus.canRetryTwoFactor).mockReturnValue(true);
    vi.mocked(campus.retryTwoFactor).mockResolvedValue({ state: "need-2fa", username: "12345678", methods: ["totp"], codeSent: false });
    renderConnection();
    fireEvent.click(screen.getByRole("button", { name: "重试验证（免重输密码）" }));
    await waitFor(() => expect(campus.retryTwoFactor).toHaveBeenCalled());
    // 重试结果回表单：回到方式选择界面
    await waitFor(() => expect(screen.getByRole("button", { name: "使用验证器" })).toBeTruthy());
  });

  it("keeps the plain login form when no credentials are held for a retry", () => {
    applySession({ state: "error", username: null, message: "验证码不正确" });
    renderConnection();
    expect(screen.queryByRole("button", { name: "重试验证（免重输密码）" })).toBeNull();
    expect(screen.getByLabelText("学号")).toBeTruthy();
  });

  it("cancels a pending two-factor login and resets the store", async () => {
    applySession({ state: "need-2fa", username: "12345678", methods: ["totp"], codeSent: true, selectedMethod: "totp" });
    vi.mocked(campus.logout).mockResolvedValue(undefined);
    renderConnection();
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    await waitFor(() => expect(campus.logout).toHaveBeenCalled());
    await waitFor(() => expect(useSessionStore.getState().status).toBe("idle"));
  });

  it("shows the connected state when the session is ready", () => {
    applySession({ state: "ready", username: "12345678" });
    renderConnection();
    expect(screen.getByText("校园会话已连接，可采集最新数据。")).toBeTruthy();
  });
});
