import { EventEnvelopeSchema, SyncCursorSchema, type EventEnvelope } from "@agenthu/contracts";
import { invoke } from "@tauri-apps/api/core";

const QUEUE_STORAGE_KEY = "agenthu.event-queue";
export const CORRUPT_QUEUE_BACKUP_KEY = "agenthu.event-queue.corrupt";

export interface EventQueue {
  add(events: EventEnvelope[]): Promise<void>;
  list(): Promise<EventEnvelope[]>;
  remove(clientEventIds: string[]): Promise<void>;
  getCursor(): Promise<string | null>;
  setCursor(cursor: string | null): Promise<void>;
}

interface QueueState {
  events: EventEnvelope[];
  cursor: string | null;
}

interface CorruptQueueBackup {
  reason: string;
  quarantined_at: string;
  value: unknown;
}

export class LocalEventQueue implements EventQueue {
  private state: QueueState;

  constructor(private readonly storage: Storage | null = typeof localStorage === "undefined" ? null : localStorage) {
    this.state = this.read();
  }

  async add(events: EventEnvelope[]): Promise<void> {
    const known = new Set(this.state.events.map((event) => event.client_event_id));
    for (const event of events) {
      if (known.has(event.client_event_id)) continue;
      this.state.events.push(event);
      known.add(event.client_event_id);
    }
    this.write();
  }

  async list(): Promise<EventEnvelope[]> {
    return [...this.state.events];
  }

  async remove(clientEventIds: string[]): Promise<void> {
    const remove = new Set(clientEventIds);
    this.state.events = this.state.events.filter((event) => !remove.has(event.client_event_id));
    this.write();
  }

  async getCursor(): Promise<string | null> {
    return this.state.cursor;
  }

  async setCursor(cursor: string | null): Promise<void> {
    this.state.cursor = cursor;
    this.write();
  }

  private read(): QueueState {
    const raw = this.storage?.getItem(QUEUE_STORAGE_KEY);
    if (!raw) return { events: [], cursor: null };

    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      this.quarantine(raw, ["queue payload is not valid JSON"]);
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
    if (problems.length > 0) this.quarantine(raw, problems);
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

  private quarantine(value: unknown, reasons: string[]): void {
    if (!this.storage) return;
    const backup: CorruptQueueBackup = {
      reason: reasons.join("; "),
      quarantined_at: new Date().toISOString(),
      value,
    };
    this.storage.setItem(CORRUPT_QUEUE_BACKUP_KEY, JSON.stringify(backup));
  }

  private write(): void {
    this.storage?.setItem(QUEUE_STORAGE_KEY, JSON.stringify(this.state));
  }
}

export class SqliteEventQueue implements EventQueue {
  async add(events: EventEnvelope[]): Promise<void> {
    await invoke("queue_add", { events: EventEnvelopeSchema.array().parse(events) });
  }
  async list(): Promise<EventEnvelope[]> {
    return EventEnvelopeSchema.array().parse(await invoke("queue_list"));
  }
  async remove(clientEventIds: string[]): Promise<void> {
    await invoke("queue_remove", { clientEventIds });
  }
  async getCursor(): Promise<string | null> {
    return SyncCursorSchema.parse({ value: await invoke("queue_get_cursor") }).value;
  }
  async setCursor(cursor: string | null): Promise<void> {
    await invoke("queue_set_cursor", { cursor });
  }
}

export function createEventQueue(): EventQueue {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window
    ? new SqliteEventQueue()
    : new LocalEventQueue();
}
