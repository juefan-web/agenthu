import { assertSafeEvent, type EventEnvelope } from "@agenthu/contracts";
import { BackendClient } from "../backend/client";
import type { EventQueue } from "./queue";

export interface SyncResult {
  sent: number;
  duplicates: number;
  rejected: number;
  rejections: Array<{ client_event_id: string; reason: string }>;
  pending: number;
}

export class EventSyncCoordinator {
  constructor(
    private readonly backend: BackendClient,
    private readonly queue: EventQueue,
  ) {}

  async enqueue(events: EventEnvelope[]): Promise<void> {
    events.forEach(assertSafeEvent);
    await this.queue.add(events);
  }

  async flush(): Promise<SyncResult> {
    const pending = await this.queue.list();
    let sent = 0;
    let duplicates = 0;
    let rejected = 0;
    const rejections: SyncResult["rejections"] = [];
    for (let index = 0; index < pending.length; index += 500) {
      const response = await this.backend.pushEvents({
        events: pending.slice(index, index + 500),
        client_cursor: await this.queue.getCursor(),
      });
      await this.queue.remove([
        ...response.accepted_event_ids,
        ...response.duplicate_event_ids,
        ...response.rejected.map((item) => item.client_event_id),
      ]);
      await this.queue.setCursor(response.next_cursor);
      sent += response.accepted_event_ids.length;
      duplicates += response.duplicate_event_ids.length;
      rejected += response.rejected.length;
      rejections.push(...response.rejected);
    }
    return {
      sent,
      duplicates,
      rejected,
      rejections,
      pending: (await this.queue.list()).length,
    };
  }
}
