import { assertSafeEvent, EventEnvelopeSchema, SyncCursorSchema, type EventEnvelope } from "@agenthu/contracts";
import { invoke } from "@tauri-apps/api/core";
import { isolateLegacyUnownedStorage, queueCorruptKey, queueKey, UNOWNED_OWNER } from "./owner";

export interface EventQueue {
  add(events: EventEnvelope[]): Promise<void>;
  list(): Promise<EventEnvelope[]>;
  remove(clientEventIds: string[]): Promise<void>;
  getCursor(): Promise<string | null>;
  setCursor(cursor: string | null): Promise<void>;
}

/** 无主数据的显式处置面（D-036：禁止自动归户，用户明确决定 adopt/discard）。
 * P0-4 数据控制页与 E7-7 的消费入口；目标 owner 的既有 cursor 优先，无主
 * cursor 仅在目标为空时并入（服务端按 client_event_id 幂等，cursor 只是
 * 顺序提示，丢弃安全）。 */
export interface UnownedQueueApi {
  countUnowned(): Promise<number>;
  adoptUnowned(targetOwnerKey: string): Promise<number>;
  discardUnowned(): Promise<number>;
}

/** P0-4 本机清理面（B 稿 §4）：owner 显式入参——清理运行在登出后，
 *  不能依赖会话现解的 owner。返回值是清除/现存的事件行数，与键存在性
 *  一起构成可复跑清理检查的判据。vacuum 仅账号删除路径置 true。 */
export interface OwnerCleanupApi {
  clearOwnerData(ownerKey: string, vacuum: boolean): Promise<number>;
  countOwnerData(ownerKey: string): Promise<number>;
}

export type OwnerResolver = () => string | null;

interface QueueState {
  events: EventEnvelope[];
  cursor: string | null;
}

interface CorruptQueueBackup {
  reason: string;
  quarantined_at: string;
  value: unknown;
}

function isStorageLike(value: Storage | LocalQueueOptions): value is Storage {
  return typeof (value as Storage).getItem === "function" && typeof (value as Storage).setItem === "function";
}

export interface LocalQueueOptions {
  storage?: Storage | null;
  /** 每次 operation 现解当前 owner：切账号后同实例自动落到新命名空间，
   * 旧账号数据原地保留（「本地删除不清另一账号」）。null → unowned。 */
  resolveOwner?: OwnerResolver;
}

export class LocalEventQueue implements EventQueue, UnownedQueueApi, OwnerCleanupApi {
  private readonly storage: Storage | null;
  private readonly resolveOwner: OwnerResolver;
  private readonly states = new Map<string, QueueState>();

  constructor(options: Storage | LocalQueueOptions = {}) {
    // 兼容旧签名 new LocalEventQueue(storage)——测试与既有调用面传普通
    // 对象 mock，不能按 instanceof Storage 判别，鸭子类型识别。
    const normalized: LocalQueueOptions = isStorageLike(options) ? { storage: options } : options;
    this.storage = normalized.storage === undefined
      ? (typeof localStorage === "undefined" ? null : localStorage)
      : normalized.storage;
    this.resolveOwner = normalized.resolveOwner ?? (() => null);
    isolateLegacyUnownedStorage(this.storage);
  }

  private owner(): string {
    return this.resolveOwner() ?? UNOWNED_OWNER;
  }

  private stateFor(owner: string): QueueState {
    let state = this.states.get(owner);
    if (!state) {
      state = this.read(owner);
      this.states.set(owner, state);
    }
    return state;
  }

  async add(events: EventEnvelope[]): Promise<void> {
    const state = this.stateFor(this.owner());
    const known = new Set(state.events.map((event) => event.client_event_id));
    for (const event of events) {
      if (known.has(event.client_event_id)) continue;
      state.events.push(event);
      known.add(event.client_event_id);
    }
    this.write(this.owner(), state);
  }

  async list(): Promise<EventEnvelope[]> {
    return [...this.stateFor(this.owner()).events];
  }

  async remove(clientEventIds: string[]): Promise<void> {
    const owner = this.owner();
    const state = this.stateFor(owner);
    const remove = new Set(clientEventIds);
    state.events = state.events.filter((event) => !remove.has(event.client_event_id));
    this.write(owner, state);
  }

  async getCursor(): Promise<string | null> {
    return this.stateFor(this.owner()).cursor;
  }

  async setCursor(cursor: string | null): Promise<void> {
    const owner = this.owner();
    this.stateFor(owner).cursor = cursor;
    this.write(owner, this.stateFor(owner));
  }

  async countUnowned(): Promise<number> {
    return this.read(UNOWNED_OWNER).events.length;
  }

  async adoptUnowned(targetOwnerKey: string): Promise<number> {
    const unowned = this.read(UNOWNED_OWNER);
    if (unowned.events.length === 0 && unowned.cursor === null) {
      this.storage?.removeItem(queueKey(UNOWNED_OWNER));
      return 0;
    }
    const target = this.stateFor(targetOwnerKey);
    const known = new Set(target.events.map((event) => event.client_event_id));
    const incoming = unowned.events.filter((event) => !known.has(event.client_event_id));
    target.events.push(...incoming);
    if (target.cursor === null) target.cursor = unowned.cursor;
    this.write(targetOwnerKey, target);
    this.states.delete(UNOWNED_OWNER);
    this.storage?.removeItem(queueKey(UNOWNED_OWNER));
    return incoming.length;
  }

  async discardUnowned(): Promise<number> {
    const unowned = this.read(UNOWNED_OWNER);
    this.states.delete(UNOWNED_OWNER);
    this.storage?.removeItem(queueKey(UNOWNED_OWNER));
    return unowned.events.length;
  }

  async clearOwnerData(ownerKey: string, _vacuum: boolean): Promise<number> {
    const count = this.read(ownerKey).events.length;
    this.states.delete(ownerKey);
    this.storage?.removeItem(queueKey(ownerKey));
    // 损坏隔离备份保留的是原 payload（用户内容面），随本 owner 一并清除
    this.storage?.removeItem(queueCorruptKey(ownerKey));
    return count;
  }

  async countOwnerData(ownerKey: string): Promise<number> {
    return this.read(ownerKey).events.length;
  }

  private read(owner: string): QueueState {
    const raw = this.storage?.getItem(queueKey(owner));
    if (!raw) return { events: [], cursor: null };

    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      this.quarantine(owner, raw, ["queue payload is not valid JSON"]);
      return { events: [], cursor: null };
    }

    // Recover events and cursor independently so damage to one field cannot
    // discard the other. The full raw payload is copied aside before anything
    // is dropped, so no pending event is lost without a recoverable record.
    const problems: string[] = [];
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      problems.push("queue payload is not an object");
    }
    const record = (typeof parsed === "object" && parsed !== null && !Array.isArray(parsed) ? parsed : {}) as Partial<QueueState>;
    const events = this.readEvents(record.events, problems);
    const cursor = this.readCursor(record.cursor, problems);
    if (problems.length > 0) this.quarantine(owner, raw, problems);
    return { events, cursor };
  }

  private readEvents(value: unknown, problems: string[]): EventEnvelope[] {
    if (value === undefined || value === null) return [];
    if (!Array.isArray(value)) {
      problems.push("queue events are not an array");
      return [];
    }
    const events: EventEnvelope[] = [];
    for (const item of value) {
      const parsed = EventEnvelopeSchema.safeParse(item);
      if (parsed.success) events.push(parsed.data);
      else problems.push("a queued event failed schema validation");
    }
    return events;
  }

  private readCursor(value: unknown, problems: string[]): string | null {
    const parsed = SyncCursorSchema.safeParse({ value: value ?? null });
    if (parsed.success) return parsed.data.value;
    problems.push("sync cursor failed schema validation");
    return null;
  }

  private quarantine(owner: string, value: unknown, reasons: string[]): void {
    if (!this.storage) return;
    const backup: CorruptQueueBackup = {
      reason: reasons.join("; "),
      quarantined_at: new Date().toISOString(),
      value,
    };
    this.storage.setItem(queueCorruptKey(owner), JSON.stringify(backup));
  }

  private write(owner: string, state: QueueState): void {
    this.storage?.setItem(queueKey(owner), JSON.stringify(state));
  }
}

export interface SqliteQueueOptions {
  resolveOwner?: OwnerResolver;
}

export class SqliteEventQueue implements EventQueue, UnownedQueueApi, OwnerCleanupApi {
  private readonly resolveOwner: OwnerResolver;

  constructor(options: SqliteQueueOptions = {}) {
    this.resolveOwner = options.resolveOwner ?? (() => null);
  }

  private owner(): string {
    return this.resolveOwner() ?? UNOWNED_OWNER;
  }

  async add(events: EventEnvelope[]): Promise<void> {
    await invoke("queue_add", { events: EventEnvelopeSchema.array().parse(events), owner: this.owner() });
  }
  async list(): Promise<EventEnvelope[]> {
    return EventEnvelopeSchema.array().parse(await invoke("queue_list", { owner: this.owner() }));
  }
  async remove(clientEventIds: string[]): Promise<void> {
    await invoke("queue_remove", { clientEventIds, owner: this.owner() });
  }
  async getCursor(): Promise<string | null> {
    return SyncCursorSchema.parse({ value: await invoke("queue_get_cursor", { owner: this.owner() }) }).value;
  }
  async setCursor(cursor: string | null): Promise<void> {
    await invoke("queue_set_cursor", { cursor, owner: this.owner() });
  }
  async countUnowned(): Promise<number> {
    return await invoke("queue_unowned_count");
  }
  async adoptUnowned(targetOwnerKey: string): Promise<number> {
    return await invoke("queue_unowned_adopt", { targetOwner: targetOwnerKey });
  }
  async discardUnowned(): Promise<number> {
    return await invoke("queue_unowned_discard");
  }
  async clearOwnerData(ownerKey: string, vacuum: boolean): Promise<number> {
    return await invoke("queue_clear_owner", { owner: ownerKey, vacuum });
  }
  async countOwnerData(ownerKey: string): Promise<number> {
    return await invoke("queue_count_owner", { owner: ownerKey });
  }
}

/** 敏感字段防线在队列边界无条件执行（B-3.2）：未配置 Backend 的直接入队路径
 *  与同步协调器共享同一条检查，不存在绕过 assertSafeEvent 的入口。 */
class SafeEventQueue implements EventQueue, UnownedQueueApi, OwnerCleanupApi {
  constructor(private readonly inner: EventQueue & Partial<UnownedQueueApi> & Partial<OwnerCleanupApi>) {}

  async add(events: EventEnvelope[]): Promise<void> {
    events.forEach(assertSafeEvent);
    await this.inner.add(events);
  }
  list(): Promise<EventEnvelope[]> { return this.inner.list(); }
  remove(clientEventIds: string[]): Promise<void> { return this.inner.remove(clientEventIds); }
  getCursor(): Promise<string | null> { return this.inner.getCursor(); }
  setCursor(cursor: string | null): Promise<void> { return this.inner.setCursor(cursor); }
  countUnowned(): Promise<number> { return this.unowned().countUnowned(); }
  adoptUnowned(targetOwnerKey: string): Promise<number> { return this.unowned().adoptUnowned(targetOwnerKey); }
  discardUnowned(): Promise<number> { return this.unowned().discardUnowned(); }
  clearOwnerData(ownerKey: string, vacuum: boolean): Promise<number> { return this.cleanup().clearOwnerData(ownerKey, vacuum); }
  countOwnerData(ownerKey: string): Promise<number> { return this.cleanup().countOwnerData(ownerKey); }

  private unowned(): UnownedQueueApi {
    if (!this.inner.countUnowned) throw new Error("当前队列实现不支持无主数据处置");
    return this.inner as UnownedQueueApi;
  }

  private cleanup(): OwnerCleanupApi {
    if (!this.inner.clearOwnerData) throw new Error("当前队列实现不支持本机清理");
    return this.inner as OwnerCleanupApi;
  }
}

export function createEventQueue(options: { resolveOwner?: OwnerResolver } = {}): EventQueue & UnownedQueueApi & OwnerCleanupApi {
  const inner = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window
    ? new SqliteEventQueue(options)
    : new LocalEventQueue(options);
  return new SafeEventQueue(inner);
}
