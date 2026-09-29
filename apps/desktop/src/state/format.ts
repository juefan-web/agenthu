/** `available_minutes` 投影值（D-027）的呈现格式：≥60 分钟 `XhYm`（整小时省
 *  `0m`），不足 1 小时 `Ym`。例：200 → `3h20m`、60 → `1h`、45 → `45m`、0 → `0m`。 */
export function formatAvailableMinutes(minutes: number): string {
  const safe = Math.max(0, Math.round(minutes));
  const hours = Math.floor(safe / 60);
  const rest = safe % 60;
  if (hours === 0) return `${rest}m`;
  return rest === 0 ? `${hours}h` : `${hours}h${rest}m`;
}
