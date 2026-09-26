/**
 * 洗衣机 —— thu-info-app 移植（apps/thu-info-app/src/ui/home/washer.tsx 与其
 * utils/washer.ts）。三家数据源都是公开服务，无需校内会话，故不走 HttpClient
 * （避免被 WebVPN 包装）：
 *
 * - 捷利      api.cleverschool.cn/washapi4（楼栋 + 设备状态）+ 校内 JieliWashers（安装位置，best-effort）
 * - 海乐生活  yshz-user.haier-ioc.com（点位 + 按品类分页设备）
 * - 小兰智慧  wash-ltd-thu.aajax.top（楼栋 + 房间/设备；上游 2026-09 新增的数据源）
 *
 * 楼栋用 provider 区分而不是布尔标记：数据源从一个变三个后，「是不是海乐」这种布尔会立刻
 * 不够用，而楼栋 id 在不同数据源之间会重名——原子深链必须带上 provider 才能回到同一台设备。
 */
import type { FetchLike } from "../http.js";

export type WasherProvider = "jieli" | "haile" | "xiaolan";

/** 数据源显示名（UI 与原子说明共用一份口径） */
export const WASHER_PROVIDER_LABEL: Record<WasherProvider, string> = {
  jieli: "捷利楼栋",
  haile: "海乐生活点位",
  xiaolan: "小兰智慧",
};

export interface WasherBuilding {
  name: string;
  id: string;
  provider: WasherProvider;
}

export interface WasherBuildingGroup {
  name: string;
  buildings: WasherBuilding[];
}

/**
 * 设备状态。上游把「离线 / 待机 / 未知」单列出来（小兰智慧有这三种），
 * 不能都塞进「故障」——离线是网络掉线，待机是可用但没启动，含义完全不同。
 */
export type WasherStatus = "idle" | "working" | "standby" | "error" | "offline" | "unknown";

export interface WasherDevice {
  /** 设备类型（洗衣机 / 洗鞋机 / 烘干机 / 洗烘一体机 / 捷利 macUnionCode 前段） */
  type: string;
  name: string;
  floor: string;
  status: WasherStatus;
  /** 剩余分钟（捷利；其余数据源无 → -1） */
  eta: number;
  /** 状态更新时间（原文，如 "10:32"） */
  updateTime: string;
  /** 安装位置（校内 JieliWashers，best-effort） */
  location?: string;
  /** 设备 id（小兰智慧有；其余数据源无） */
  id?: string;
}

/* ══════════ provider 与原子 key 的编码约定 ══════════
 * 原子 key 第三段存数据源代码："0" 捷利 / "1" 海乐生活 / "2" 小兰智慧。
 * 历史收藏里只有 "0"/"1"，故缺省与空值一律按捷利解释，老收藏照常能回到原位。 */

export function washerProviderCode(provider: WasherProvider): string {
  return provider === "haile" ? "1" : provider === "xiaolan" ? "2" : "0";
}

export function washerProviderOf(code: string | undefined | null): WasherProvider {
  return code === "1" ? "haile" : code === "2" ? "xiaolan" : "jieli";
}

/** 实时缓存键后缀（各数据源的楼栋 id 可能相同，必须分开缓存） */
export function washerCacheSuffix(code: string | undefined | null): string {
  return washerProviderOf(code) === "haile" ? "h" : washerProviderOf(code) === "xiaolan" ? "x" : "j";
}

async function postJson<T>(fetchLike: FetchLike, url: string, body: unknown): Promise<T> {
  const res = await fetchLike(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const text = await res.text();
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new Error(`洗衣机服务响应异常（HTTP ${res.status}）`);
  }
}

/** 楼栋名排序：先按名字里的数字，再按字典序（washer.tsx 同款规则） */
function compareBuilding(a: WasherBuilding, b: WasherBuilding): number {
  const an = /\d+/.exec(a.name)?.[0];
  const bn = /\d+/.exec(b.name)?.[0];
  if (an !== undefined && bn !== undefined) {
    const diff = Number.parseInt(an, 10) - Number.parseInt(bn, 10);
    if (diff !== 0) return diff;
  }
  return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
}

/** 设备名按中文数字序排（"洗衣机2" 排在 "洗衣机10" 前面） */
export function compareWasherNames(a: string, b: string): number {
  return a.localeCompare(b, "zh-CN", { numeric: true });
}

/* ══════════ 捷利 ══════════ */

async function getJieliGroups(fetchLike: FetchLike): Promise<WasherBuildingGroup[]> {
  const groups: WasherBuildingGroup[] = [
    { name: "紫荆公寓", buildings: [] },
    { name: "南区宿舍", buildings: [] },
    { name: "双清公寓", buildings: [] },
    { name: "其他位置", buildings: [] },
  ];
  const towers = await postJson<{
    errorCode?: unknown;
    errorMsg?: string;
    data?: Array<{ text?: string; value?: string }>;
  }>(fetchLike, "https://api.cleverschool.cn/washapi4/device/tower", {});
  if (towers.errorCode != null) throw new Error(towers.errorMsg || "洗衣机楼栋列表获取失败");
  const byName = new Map(groups.map((g) => [g.name, g]));
  for (const b of towers.data ?? []) {
    const text = String(b.text ?? "");
    const value = String(b.value ?? "");
    if (!text || value === "0" || value === "") continue;
    const building: WasherBuilding = { name: text, id: value, provider: "jieli" };
    const group = text.includes("紫荆")
      ? byName.get("紫荆公寓")
      : text.includes("南区")
        ? byName.get("南区宿舍")
        : text.includes("双清")
          ? byName.get("双清公寓")
          : byName.get("其他位置");
    group?.buildings.push(building);
  }
  for (const g of groups) g.buildings.sort(compareBuilding);
  return groups;
}

/* ══════════ 海乐生活 ══════════ */

/** 清华两个校区的坐标（上游 HAIER_SEARCH_POSITIONS 同款；只取名字含「清华」的点位） */
const HAIER_SEARCH_POSITIONS = [
  { lng: 116.32697, lat: 40.00281 },
  { lng: 116.3424247, lat: 40.0313472 },
];

async function getHaileGroups(fetchLike: FetchLike): Promise<WasherBuildingGroup[]> {
  const responses = await Promise.all(
    HAIER_SEARCH_POSITIONS.map((position) =>
      postJson<{ code?: number; data?: { items?: Array<{ id?: string | number; name?: string }> } }>(
        fetchLike,
        "https://yshz-user.haier-ioc.com/position/nearPosition",
        { ...position, page: 1, pageSize: 50 },
      ).catch(() => null),
    ),
  );
  const byId = new Map<string, WasherBuilding>();
  for (const res of responses) {
    if (!res || res.code !== 0) continue;
    for (const b of res.data?.items ?? []) {
      const name = String(b.name ?? "");
      // 「清华中学」不是校内点位：上游同样排除
      if (!name.includes("清华") || name.includes("中学") || b.id === undefined) continue;
      const id = String(b.id);
      byId.set(id, { name, id, provider: "haile" });
    }
  }
  return [{ name: "海乐生活", buildings: [...byId.values()].sort(compareBuilding) }];
}

/* ══════════ 小兰智慧（上游 2026-09 新增） ══════════ */

/**
 * 小兰智慧经第三方代理访问（上游同款）：代理按机构 id 分组返回楼栋与房间/设备。
 * 故解析要按「机构 → 楼栋 → 房间（facilities）→ 设备（devices）」逐层取，
 * 且**任一层缺失就整体报错**——宁可显示「加载失败」，也不要把半截数据摆到用户面前。
 */
const XIAOLAN_URL = "https://wash-ltd-thu.aajax.top";
const XIAOLAN_ORGANIZATION = "67ce4044ba854c556508830e";

function asObject(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function asLabel(value: unknown, fallback = ""): string {
  return typeof value === "string" && value.length > 0 ? value : typeof value === "number" ? String(value) : fallback;
}

/**
 * 时间字段 → 毫秒。实测小兰的 `estimatedCompleteTime` 是**毫秒时间戳数字**
 * （如 1789890813708），而上游的 date() 同时兼容数字与字符串——两种形态都要认，
 * 只认字符串会让「预计剩余」永远是 -1（实测踩到过一次）。
 */
function asMillis(value: unknown): number {
  if (typeof value === "number") return Number.isFinite(value) ? value : Number.NaN;
  if (typeof value === "string" && value.length > 0) {
    if (/^\d{11,}$/.test(value)) return Number(value);          // 纯数字串：也按时间戳算
    const t = new Date(value).getTime();
    return Number.isFinite(t) ? t : Number.NaN;
  }
  return Number.NaN;
}

async function fetchXiaolan(fetchLike: FetchLike, path: string): Promise<{ buildings: Record<string, unknown> }> {
  const res = await fetchLike(`${XIAOLAN_URL}${path}`);
  if (!res.ok) throw new Error(`小兰智慧服务响应异常（HTTP ${res.status}）`);
  const data = asObject(await res.json());
  const org = asObject(data[XIAOLAN_ORGANIZATION]);
  const buildings = org.buildings;
  if (!buildings || typeof buildings !== "object" || Array.isArray(buildings)) {
    throw new Error("小兰智慧数据格式异常");
  }
  return { buildings: buildings as Record<string, unknown> };
}

/** 设备状态：离线 > 故障 > 运行状态（7 空闲 / 5 使用中 / 1 待机 / 其余未知） */
export function xiaolanStatus(deviceState: unknown): WasherStatus {
  const state = asObject(deviceState);
  const online = state.isOnline;
  if (online === 0 || online === "0") return "offline";
  const fault = state.fault;
  if (fault != null && fault !== 0 && fault !== "0" && fault !== false && fault !== "") return "error";
  if (online !== 1 && online !== "1") return "unknown";
  switch (Number(state.runState)) {
    case 7: return "idle";
    case 5: return "working";
    case 1: return "standby";
    default: return "unknown";
  }
}

/** 设备类型码 → 名称（上游同款 1/2/3/4） */
const XIAOLAN_TYPES: Record<string, string> = {
  "1": "洗衣机",
  "2": "烘干机",
  "3": "洗烘一体机",
  "4": "洗鞋机",
};

async function getXiaolanGroups(fetchLike: FetchLike): Promise<WasherBuildingGroup[]> {
  const { buildings } = await fetchXiaolan(fetchLike, "/buildings/list");
  const list = Object.entries(buildings).map(([id, value]): WasherBuilding => {
    const b = asObject(value);
    return { id: asLabel(b.buildingId, id), name: asLabel(b.name, id), provider: "xiaolan" };
  });
  list.sort((a, b) => compareWasherNames(a.name, b.name));
  return [{ name: "小兰智慧", buildings: list }];
}

/** 小兰智慧楼栋 → 房间（每个房间自成一「层」，名称里带楼层）与设备 */
async function getXiaolanDevices(fetchLike: FetchLike, buildingId: string): Promise<Array<{ floor: string; washers: WasherDevice[] }>> {
  const { buildings } = await fetchXiaolan(fetchLike, `/buildings/${encodeURIComponent(buildingId)}`);
  const building = asObject(buildings[buildingId] ?? Object.values(buildings)[0]);
  const facilities = building.facilities;
  if (!Array.isArray(facilities)) throw new Error("小兰智慧数据格式异常");

  const rooms: Array<{ order: string; floor: string; washers: WasherDevice[] }> = [];
  for (const raw of facilities) {
    const facility = asObject(raw);
    const store = asObject(facility.store);
    const detail = asObject(facility.storeDetail);
    const roomName = asLabel(detail.name, asLabel(store.opStoreName, "洗衣房"));
    const floorNo = asLabel(store.floor);
    if (!Array.isArray(facility.devices)) throw new Error("小兰智慧数据格式异常");
    const washers: WasherDevice[] = facility.devices.map((rawDevice): WasherDevice => {
      const device = asObject(rawDevice);
      const id = asLabel(device.deviceId);
      const inUse = asObject(device.inUseBit);
      const etaMs = asMillis(inUse.estimatedCompleteTime);
      const status = xiaolanStatus(device.deviceState);
      // 预计完成时间 → 剩余分钟（上游只给时间点，剩余分钟要自己算；已过期按 0）
      const eta = status === "working" && Number.isFinite(etaMs) ? Math.max(0, Math.round((etaMs - Date.now()) / 60_000)) : -1;
      return {
        id,
        type: XIAOLAN_TYPES[asLabel(device.type)] ?? "洗衣机",
        name: asLabel(device.deviceCode, id),
        floor: roomName,
        status,
        eta,
        updateTime: "",
      };
    });
    washers.sort((a, b) => compareWasherNames(a.name, b.name));
    rooms.push({ order: `${floorNo} ${roomName}`, floor: roomName, washers });
  }
  rooms.sort((a, b) => compareWasherNames(a.order, b.order));
  return rooms.map(({ floor, washers }) => ({ floor, washers }));
}

/* ══════════ 对外接口 ══════════ */

/**
 * 楼栋分组。三家数据源各自独立容错：某一家挂了只少这一组，不能让另外两家也打不开
 * （捷利是主源，它失败才整体抛错）。
 */
export async function getWasherBuildingGroups(fetchLike: FetchLike): Promise<WasherBuildingGroup[]> {
  const jieli = await getJieliGroups(fetchLike);
  const rest: WasherBuildingGroup[] = [];
  try {
    rest.push(...(await getHaileGroups(fetchLike)));
  } catch {
    /* 海乐生活点位失败可容忍（上游同款：静默跳过） */
  }
  try {
    const xl = await getXiaolanGroups(fetchLike);
    if (xl[0]?.buildings.length) rest.push(...xl);
  } catch {
    /* 小兰智慧是第三方代理，失败可容忍 */
  }
  return [...jieli, ...rest];
}

/** 楼栋内设备（按数据源分流） */
export async function getWasherDevices(
  fetchLike: FetchLike,
  building: WasherBuilding,
): Promise<Array<{ floor: string; washers: WasherDevice[] }>> {
  if (building.provider === "xiaolan") return getXiaolanDevices(fetchLike, building.id);
  if (building.provider === "haile") return getHaileDevices(fetchLike, building.id);
  return getJieliDevices(fetchLike, building.id);
}

async function getHaileDevices(fetchLike: FetchLike, buildingId: string): Promise<Array<{ floor: string; washers: WasherDevice[] }>> {
  const typeNames: Record<string, string> = { "00": "洗衣机", "01": "洗鞋机", "02": "烘干机" };
  const statusMap: Record<number, WasherStatus> = { 1: "idle", 2: "working", 3: "error" };
  const washers: WasherDevice[] = [];
  for (const catCode of ["00", "01", "02"]) {
    const detail = await postJson<{ code?: number; data?: { items?: Array<{ name?: string; state?: number }> } }>(
      fetchLike,
      "https://yshz-user.haier-ioc.com/position/deviceDetailPage",
      { positionId: buildingId, categoryCode: catCode, page: 1, floorCode: "", pageSize: 100 },
    ).catch(() => null);
    if (!detail || detail.code !== 0) continue;
    for (const w of detail.data?.items ?? []) {
      washers.push({
        type: typeNames[catCode] ?? "洗衣机",
        name: String(w.name ?? ""),
        floor: "海乐生活",
        status: statusMap[Number(w.state)] ?? "unknown",
        eta: -1,
        updateTime: "",
      });
    }
  }
  washers.sort((a, b) => compareWasherNames(a.name, b.name));
  return [{ floor: "海乐生活", washers }];
}

/**
 * 捷利设备（washer.tsx WasherDetailScreen 同款解析）：
 * status 串「待机/工作/运转/剩余:NN分钟/更新:HH:MM」逐段判读，安装位置来自校内接口（best-effort）。
 */
async function getJieliDevices(fetchLike: FetchLike, buildingId: string): Promise<Array<{ floor: string; washers: WasherDevice[] }>> {
  const [statusRes, locRes] = await Promise.allSettled([
    postJson<{
      errorCode?: unknown;
      errorMsg?: string;
      data?: Array<{ floorName?: string; macUnionCode?: string; status?: string }>;
    }>(fetchLike, "https://api.cleverschool.cn/washapi4/device/status", { towerKey: buildingId }),
    fetchLike(`https://app.cs.tsinghua.edu.cn/Api/JieliWashers?building=${encodeURIComponent(buildingId)}`)
      .then((r) => r.json() as Promise<Record<string, string>>)
      .catch(() => ({} as Record<string, string>)),
  ]);
  if (statusRes.status === "rejected") {
    throw statusRes.reason instanceof Error ? statusRes.reason : new Error("洗衣机状态获取失败");
  }
  const payload = statusRes.value;
  if (payload.errorCode != null) throw new Error(payload.errorMsg || "洗衣机状态获取失败");

  const byFloor = new Map<string, WasherDevice[]>();
  for (const item of payload.data ?? []) {
    const floor = String(item.floorName ?? "未知楼层");
    const parts = String(item.status ?? "").split(" ");
    let status: WasherStatus = "error";
    let eta = 0;
    let updateTime = "";
    for (const seg of parts) {
      if (seg.includes("剩余")) eta = Number(/\d+/.exec(seg)?.[0] ?? 0) || 0;
      else if (seg.includes("更新")) updateTime = seg.split(":").slice(1).join(":").trim();
      else if (seg.includes("待机")) status = "idle";
      else if (seg.includes("工作") || seg.includes("运转")) status = "working";
    }
    const code = String(item.macUnionCode ?? "").split(" ");
    const list = byFloor.get(floor) ?? [];
    list.push({
      type: code[0] ?? "",
      name: code[1] ?? code[0] ?? "",
      floor,
      status,
      eta,
      updateTime,
      location: locRes.status === "fulfilled" ? (locRes.value as Record<string, string>)[code[1] ?? ""] : undefined,
    });
    byFloor.set(floor, list);
  }
  const out: Array<{ floor: string; washers: WasherDevice[] }> = [];
  for (const [floor, washers] of byFloor) {
    washers.sort((a, b) => compareWasherNames(a.name, b.name));
    out.push({ floor, washers });
  }
  return out;
}
