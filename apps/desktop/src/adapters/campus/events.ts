import type { EventEnvelope } from "@agenthu/contracts";
import type {
  CampusAssignment,
  CampusCalendar,
  CampusCourse,
  CampusScheduleEntry,
} from "./types";

export const ONETHU_CONNECTOR_VERSION = "2e3455fc235719b7f91fffaf5fe35e09220dda73";

function semanticVersion(data: Record<string, unknown>): string {
  const serialized = JSON.stringify(data);
  let hash = 2166136261;
  for (let index = 0; index < serialized.length; index += 1) {
    hash ^= serialized.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

/** 校园门户时间串固定为北京本地（vendor naive，如 "2026-09-28 23:59"）；
 *  D-028 §3：deadline 类字段 naive 会被 Backend 拒收，统一按 +08:00 解释。 */
const CAMPUS_OFFSET = "+08:00";
const NAIVE_DATETIME = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?$/;
const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;

/** vendor naive 串 → `+08:00` tz-aware ISO；date-only → 北京本地零点；
 *  已带偏移/Z 的原样透传。不可识别形态返回 null（不猜测，交给边界拒收/留空）。
 *  取代旧 asIso 的 `new Date()` 解释——那是宿主 OS 本地时区，北京之外的
 *  机器上 occurred_at 会整体偏移。 */
export function asCampusIso(value: string | null | undefined): string | null {
  if (!value) return null;
  const trimmed = value.trim();
  if (NAIVE_DATETIME.test(trimmed)) return `${trimmed.replace(" ", "T")}${CAMPUS_OFFSET}`;
  if (DATE_ONLY.test(trimmed)) return `${trimmed}T00:00:00${CAMPUS_OFFSET}`;
  return Number.isNaN(Date.parse(trimmed)) ? null : trimmed;
}

function eventBase(
  type: string,
  upstreamId: string,
  occurredAt: string,
  fetchedAt: string,
  data: Record<string, unknown>,
  context: Record<string, unknown> = {},
): EventEnvelope {
  const version = semanticVersion(data);
  return {
    client_event_id: `onethu:${upstreamId}:${version}`,
    type,
    occurred_at: occurredAt,
    source: "onethu",
    data,
    context,
    provenance: {
      connector: "onethu",
      connector_version: ONETHU_CONNECTOR_VERSION,
      upstream_id: upstreamId,
      semantic_version: version,
      fetched_at: fetchedAt,
    },
  };
}

export function mapCourseEvent(course: CampusCourse, fetchedAt: string): EventEnvelope {
  return eventBase(
    "study.course.discovered",
    `course:${course.id}`,
    fetchedAt,
    fetchedAt,
    {
      course_id: course.id,
      name: course.name,
      english_name: course.englishName,
      course_number: course.courseNumber,
      teacher_name: course.teacherName,
      time_and_location: course.timeAndLocation,
      url: course.url,
    },
    { domain: "study" },
  );
}

export function mapAssignmentEvent(assignment: CampusAssignment, fetchedAt: string): EventEnvelope {
  const type = assignment.submitted || assignment.graded
    ? "study.assignment.updated"
    : "study.assignment.discovered";
  return eventBase(
    type,
    `assignment:${assignment.id}`,
    // occurred_at 同口径按北京本地解释（原串留 publish_time_raw/deadline_raw）
    asCampusIso(assignment.publishTime || assignment.deadline) ?? fetchedAt,
    fetchedAt,
    {
      assignment_id: assignment.id,
      course_id: assignment.courseId,
      // L3：供后端派生标题「{course_name}：{title}」；缺失为 null（旧载荷兼容分支）
      course_name: assignment.courseName ?? null,
      title: assignment.title,
      content: assignment.content,
      publish_time: asCampusIso(assignment.publishTime),
      publish_time_raw: assignment.publishTime ?? null,
      deadline: asCampusIso(assignment.deadline),
      deadline_raw: assignment.deadline ?? null,
      late_deadline: asCampusIso(assignment.lateDeadline),
      late_deadline_raw: assignment.lateDeadline ?? null,
      submitted: assignment.submitted,
      graded: assignment.graded,
      url: assignment.url,
    },
    { domain: "study", course_id: assignment.courseId },
  );
}

export function mapScheduleEvent(entry: CampusScheduleEntry, fetchedAt: string): EventEnvelope {
  const upstreamId = [
    entry.courseName,
    entry.date ?? "unknown-date",
    entry.startSection ?? "unknown-start",
    entry.endSection ?? "unknown-end",
  ].join("|");
  return eventBase(
    "time.schedule.entry",
    `schedule:${upstreamId}`,
    // date-only 按北京本地零点（旧实现的 UTC 零点 = 北京 08:00，偏 8 小时）
    asCampusIso(entry.date) ?? fetchedAt,
    fetchedAt,
    {
      course_name: entry.courseName,
      teacher: entry.teacher ?? null,
      date: entry.date ?? null,
      day_of_week: entry.dayOfWeek ?? null,
      start_section: entry.startSection ?? null,
      end_section: entry.endSection ?? null,
      location: entry.location ?? null,
      week_text: entry.weekText ?? null,
      category: entry.category ?? null,
      start_time: entry.startTime ?? null,
      end_time: entry.endTime ?? null,
    },
    { domain: "time" },
  );
}

export function mapCalendarEvent(calendar: CampusCalendar, fetchedAt: string): EventEnvelope {
  return eventBase(
    "time.academic_calendar.updated",
    `calendar:${calendar.semesterId}`,
    fetchedAt,
    fetchedAt,
    {
      first_day: calendar.firstDay,
      semester_id: calendar.semesterId,
      semester_name: calendar.semesterName,
      week_count: calendar.weekCount,
      next_semester_list: calendar.nextSemesterList,
    },
    { domain: "time" },
  );
}
