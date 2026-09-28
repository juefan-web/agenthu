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

function asIso(value: string | undefined, fallback: string): string {
  if (!value) return fallback;
  const parsed = new Date(value.replace(" ", "T"));
  return Number.isNaN(parsed.getTime()) ? fallback : parsed.toISOString();
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
    asIso(assignment.publishTime || assignment.deadline, fetchedAt),
    fetchedAt,
    {
      assignment_id: assignment.id,
      course_id: assignment.courseId,
      title: assignment.title,
      content: assignment.content,
      publish_time: assignment.publishTime,
      deadline: assignment.deadline,
      late_deadline: assignment.lateDeadline ?? null,
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
    asIso(entry.date, fetchedAt),
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
