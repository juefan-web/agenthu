import { useCallback, useEffect, useRef, useState } from "react";
import type { DataOperationOut } from "@agenthu/contracts";
import { isTerminalStatus } from "./statusCopy";

/** B 稿 §2 poll 参数（冻结）：5s 起步、退避至 30s、前台上限 30 分钟、
 *  后台暂停（visibilitychange）、重挂载即新鲜拉取；手动查询只 GET。
 *  账号删除不走本钩子（确认后 owner 认证失效，状态面移交回执视图）。 */

export const POLL_INITIAL_DELAY_MS = 5_000;
export const POLL_MAX_DELAY_MS = 30_000;
export const POLL_TOTAL_CAP_MS = 30 * 60_000;

export function nextPollDelayMs(currentDelayMs: number): number {
  return Math.min(currentDelayMs * 2, POLL_MAX_DELAY_MS);
}

export interface OperationPollOptions {
  operationId: string | null;
  fetchOperation: (operationId: string) => Promise<DataOperationOut>;
  onTerminal?: (operation: DataOperationOut) => void;
}

export interface OperationPollState {
  operation: DataOperationOut | null;
  /** 30 分钟上限到：停止自动轮询，仅手动刷新（GET）。 */
  capped: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function useOperationPoll(options: OperationPollOptions): OperationPollState {
  const { operationId, fetchOperation, onTerminal } = options;
  const [operation, setOperation] = useState<DataOperationOut | null>(null);
  const [capped, setCapped] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const delayRef = useRef(POLL_INITIAL_DELAY_MS);
  const elapsedRef = useRef(0);
  const aliveRef = useRef(true);
  const terminalRef = useRef<DataOperationOut | null>(null);
  const onTerminalRef = useRef(onTerminal);
  onTerminalRef.current = onTerminal;

  const clearTimer = () => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };

  const refresh = useCallback(async () => {
    if (!operationId || terminalRef.current) return;
    try {
      const next = await fetchOperation(operationId);
      if (!aliveRef.current) return;
      setError(null);
      setOperation(next);
      if (isTerminalStatus(next.status)) {
        terminalRef.current = next;
        clearTimer();
        onTerminalRef.current?.(next);
      }
    } catch (cause) {
      if (!aliveRef.current) return;
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }, [fetchOperation, operationId]);

  useEffect(() => {
    aliveRef.current = true;
    terminalRef.current = null;
    delayRef.current = POLL_INITIAL_DELAY_MS;
    elapsedRef.current = 0;
    setOperation(null);
    setCapped(false);
    setError(null);
    if (!operationId) return;

    // 重挂载即新鲜拉取（不等待首个 5s）
    void refresh();

    const schedule = () => {
      if (terminalRef.current) return;
      clearTimer();
      timerRef.current = setTimeout(() => {
        elapsedRef.current += delayRef.current;
        if (elapsedRef.current >= POLL_TOTAL_CAP_MS) {
          setCapped(true);
          clearTimer();
          return;
        }
        delayRef.current = nextPollDelayMs(delayRef.current);
        void refresh().then(() => {
          if (aliveRef.current) schedule();
        });
      }, delayRef.current);
    };
    schedule();

    const onVisibility = () => {
      if (document.visibilityState === "hidden") {
        clearTimer();
      } else if (!terminalRef.current) {
        // 回前台：立即新鲜拉取并恢复梯子
        void refresh().then(() => {
          if (aliveRef.current && document.visibilityState === "visible") schedule();
        });
      }
    };
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      aliveRef.current = false;
      clearTimer();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [operationId, refresh]);

  return { operation, capped, error, refresh };
}
