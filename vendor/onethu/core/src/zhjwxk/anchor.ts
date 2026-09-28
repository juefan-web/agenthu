/**
 * CR 课表格子 id → 节次与星期。
 *
 * 口径与 info app 的 `parseScript` 完全一致：格子 id 形如 **`a{session}_{day}`**，
 * 即 `basic[1]` 是**节次（大节 1~6）**、`basic[3]` 是**星期（1~7）**。
 *
 * 2026-09-20 真机实录（实验室科研探究 / 二级课表）：
 *   `a4_5` ↔ overlib `04_54( 待定，第4周)` = 周五（5）第4大节（4）
 *   `a4_4` ↔ `05_44(…)`、`a3_3` ↔ `06_33(…)` —— 提示串末两位是「周+节」，
 *   与格子 id 正好倒序。我们此前把 `anchor[0]` 当星期、`anchor[1]` 当节次，
 *   于是「周5第4大节」被读成「周4第5大节」：二级课表里实验室课整体错位，
 *   并因此和主课表里的同一门课错开时间显示成两份。
 */
export function parseCellAnchor(gridId: string): { session: number; day: number } | null {
  const anchor = String(gridId ?? "").split(/[a_]/).filter(Boolean);
  const session = Number(anchor[0]);
  const day = Number(anchor[1]);
  if (!Number.isInteger(session) || !Number.isInteger(day)) return null;
  if (session < 1 || session > 6 || day < 1 || day > 7) return null;
  return { session, day };
}
