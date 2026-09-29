import { exec, spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { unlink } from "node:fs/promises";
import { basename } from "node:path";
import { promisify } from "node:util";

const execAsync = promisify(exec);

/** campus.hold 由 Rust snapshot_path 落在 app_local_data_dir（Windows 即
 *  %LOCALAPPDATA%/<identifier>）。可用 AGENTHU_CAMPUS_HOLD 覆盖。 */
export function campusHoldPath(): string {
  return process.env.AGENTHU_CAMPUS_HOLD
    ?? `${process.env.LOCALAPPDATA}\\dev.agenthu.desktop\\campus.hold`;
}

async function cdpReachable(cdpUrl: string): Promise<boolean> {
  try {
    const response = await fetch(`${cdpUrl}/json/version`);
    return response.ok;
  } catch {
    return false;
  }
}

async function sleep(ms: number): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForCdpState(cdpUrl: string, wantReachable: boolean, timeoutMs: number, label: string): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if ((await cdpReachable(cdpUrl)) === wantReachable) return;
    await sleep(500);
  }
  throw new Error(`等待 CDP ${cdpUrl} ${label} 超时（${timeoutMs}ms）`);
}

/** 清 campus.hold 并重启构建包（round5 E 组修订）：登录表单存在的保证来自
 *  「全新指纹」前置态。文件被 Rust 侧持有，必须先退出包进程再删；旧实例
 *  的 WebView2 调试端口要等释放，新实例才绑得上。需要 AGENTHU_APP_EXE。 */
export async function restartAppWithFreshCampusSession(cdpUrl: string): Promise<void> {
  const appExe = process.env.AGENTHU_APP_EXE;
  if (!appExe || !existsSync(appExe)) {
    throw new Error(
      "需要 AGENTHU_APP_EXE 指向构建包 exe 完成「清 campus.hold → 重启包」前置态；" +
        "或按 tests/e2e/README 手动执行后重跑",
    );
  }

  await execAsync(`taskkill /F /IM ${JSON.stringify(basename(appExe))}`).catch(() => undefined);
  await waitForCdpState(cdpUrl, false, 15_000, "随旧实例退出而释放");

  const hold = campusHoldPath();
  for (let attempt = 0; ; attempt += 1) {
    try {
      await unlink(hold);
      break;
    } catch (error) {
      const code = (error as NodeJS.ErrnoException).code;
      if (code === "ENOENT") break;
      if (attempt >= 9) throw new Error(`删除 ${hold} 失败（${code}）：确认包进程已完全退出`);
      await sleep(500);
    }
  }

  spawn(appExe, [], {
    detached: true,
    stdio: "ignore",
    env: {
      ...process.env,
      WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: `--remote-debugging-port=${new URL(cdpUrl).port}`,
    },
  }).unref();
  await waitForCdpState(cdpUrl, true, 60_000, "就绪");
}
