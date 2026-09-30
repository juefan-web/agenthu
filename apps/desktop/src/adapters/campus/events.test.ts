import { describe, expect, it } from "vitest";
import type { CampusAssignment, CampusScheduleEntry } from "./types";
import { asCampusIso, mapAssignmentEvent, mapScheduleEvent } from "./events";

const assignment: CampusAssignment = {
  id: "hw-1",
  courseId: "course-1",
  title: "线性代数 HW1",
  content: "完成练习",
  publishTime: "2026-09-26 09:00",
  deadline: "2026-09-28 23:59",
  lateDeadline: "2026-09-29 23:59",
  submitted: false,
  graded: false,
  url: "https://learn.tsinghua.edu.cn/hw-1",
};

const FETCHED_AT = "2026-09-29T10:00:00.000Z";

describe("asCampusIso", () => {
  it("interprets vendor naive datetimes as Beijing local time", () => {
    expect(asCampusIso("2026-09-28 23:59")).toBe("2026-09-28T23:59+08:00");
    expect(asCampusIso("2026-09-26 09:00:30")).toBe("2026-09-26T09:00:30+08:00");
    expect(asCampusIso("2026-09-28T23:59")).toBe("2026-09-28T23:59+08:00");
  });

  it("anchors date-only values to Beijing midnight", () => {
    expect(asCampusIso("2026-09-28")).toBe("2026-09-28T00:00:00+08:00");
  });

  it("passes through offset-aware values and rejects garbage without guessing", () => {
    expect(asCampusIso("2026-09-28T23:59:00Z")).toBe("2026-09-28T23:59:00Z");
    expect(asCampusIso("2026-09-28T23:59:00+08:00")).toBe("2026-09-28T23:59:00+08:00");
    expect(asCampusIso("not a date")).toBeNull();
    expect(asCampusIso("")).toBeNull();
    expect(asCampusIso(undefined)).toBeNull();
  });
});

describe("mapAssignmentEvent", () => {
  it("sends tz-aware deadlines with raw strings preserved (D-028 §3)", () => {
    const event = mapAssignmentEvent(assignment, FETCHED_AT);
    expect(event.data.deadline).toBe("2026-09-28T23:59+08:00");
    expect(event.data.late_deadline).toBe("2026-09-29T23:59+08:00");
    expect(event.data.publish_time).toBe("2026-09-26T09:00+08:00");
    expect(event.data.deadline_raw).toBe("2026-09-28 23:59");
    expect(event.data.late_deadline_raw).toBe("2026-09-29 23:59");
    expect(event.data.publish_time_raw).toBe("2026-09-26 09:00");
    // occurred_at 同口径：naive publishTime 按北京本地解释，不再依赖宿主时区
    expect(event.occurred_at).toBe("2026-09-26T09:00+08:00");
  });

  it("forwards course_name for derived-title synthesis and nulls it when unknown (L3)", () => {
    const withCourse = mapAssignmentEvent({ ...assignment, courseName: "线性代数(1)" }, FETCHED_AT);
    expect(withCourse.data.course_name).toBe("线性代数(1)");
    const withoutCourse = mapAssignmentEvent(assignment, FETCHED_AT);
    expect(withoutCourse.data.course_name).toBeNull();
  });

  it("falls back to fetchedAt for occurred_at only when the vendor strings are unusable", () => {
    const event = mapAssignmentEvent(
      { ...assignment, publishTime: "", deadline: "" },
      FETCHED_AT,
    );
    expect(event.occurred_at).toBe(FETCHED_AT);
    expect(event.data.deadline).toBeNull();
    expect(event.data.deadline_raw).toBe("");
  });

  it("keeps semantic_version stable per identical payload and stable across host timezones", () => {
    const first = mapAssignmentEvent(assignment, FETCHED_AT);
    const second = mapAssignmentEvent(assignment, "2026-10-01T08:00:00.000Z");
    // 语义版本只由 data 决定（fetched_at 不同不影响身份）
    expect(second.provenance.semantic_version).toBe(first.provenance.semantic_version);
    const changed = mapAssignmentEvent({ ...assignment, deadline: "2026-09-30 23:59" }, FETCHED_AT);
    expect(changed.provenance.semantic_version).not.toBe(first.provenance.semantic_version);
    expect(changed.client_event_id).not.toBe(first.client_event_id);
  });
});

describe("mapScheduleEvent", () => {
  it("anchors date-only occurred_at to Beijing midnight, not UTC midnight", () => {
    const entry: CampusScheduleEntry = {
      courseName: "线性代数",
      date: "2026-09-28",
      startSection: 1,
      endSection: 2,
      location: "六教",
    };
    const event = mapScheduleEvent(entry, FETCHED_AT);
    expect(event.occurred_at).toBe("2026-09-28T00:00:00+08:00");
    // D-027 投影消费的 data 形态不变
    expect(event.data.date).toBe("2026-09-28");
    expect(event.data.start_time).toBeNull();
  });
});
