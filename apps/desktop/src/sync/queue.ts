import { EventEnvelopeSchema, SyncCursorSchema, type EventEnvelope } from "@agenthu/contracts";
import { invoke } from "@tauri-apps/api/core";

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
    const raw = this.storage?.getItem("agenthu.event-queue");
    if (!raw) return { events: [], cursor: null };
    try {
      const parsed = JSON.parse(raw) as QueueState;
      return {
        events: EventEnvelopeSchema.array().parse(parsed.events),
        cursor: SyncCursorSchema.parse({ value: parsed.cursor }).value,
      };
    } catch {
      return { events: [], cursor: null };
    }
  }

  private write(): void {
    this.storage?.setItem("agenthu.event-queue", JSON.stringify(this.state));
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
