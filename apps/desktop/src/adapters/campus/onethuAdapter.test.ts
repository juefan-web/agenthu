import { describe, expect, it } from "vitest";
import type { CampusSession } from "@onethu/core";
import { OneThuCampusAdapter } from "./onethuAdapter";
import type { CampusAuthGateway, LoginInput, SessionStatus, Verify2FAInput } from "./types";
import { mapAssignmentEvent, mapScheduleEvent } from "./events";

function fakeSession() {
  return {
    state: "ready" as const,
    learn: {
      csrfToken: "fixture-csrf",
      resume: async () => true,
      getCurrentSemester: async () => ({ id: "2026-2027-1" }),
      getCourseList: async () => [
        {
          id: "course-1",
          name: "线性代数",
          englishName: "Linear Algebra",
          courseNumber: "00420052",
          courseIndex: 1,
          teacherName: "Teacher",
          timeAndLocation: ["周一 1-2节"],
          url: "https://learn.tsinghua.edu.cn/course-1",
        },
      ],
      getAllHomework: async () => [
        {
          id: "hw-1",
          courseId: "course-1",
          title: "HW1",
          content: "完成练习",
          publishTime: "2026-09-26 09:00",
          deadline: "2026-09-28 23:59",
          submitted: false,
          graded: false,
          url: "https://learn.tsinghua.edu.cn/hw-1",
        },
      ],
      getCalendarData: async () => ({
        firstDay: "2026-09-07",
        semesterId: "2026-2027-1",
        semesterName: "2026-2027秋季学期",
        weekCount: 20,
        nextSemesterList: [],
      }),
    },
    info: {
      getSchedule: async () => [
        {
          courseName: "线性代数",
          date: "2026-09-28",
          startSection: 1,
          endSection: 2,
          location: "六教",
          raw: {},
        },
      ],
    },
    reset() {},
  } as unknown as CampusSession;
}

const auth: CampusAuthGateway = {
  restore: async () => ({ state: "ready", username: "u" }),
  login: async (_input: LoginInput) => ({ state: "ready", username: "u" }),
  send2fa: async () => ({ state: "need-2fa", username: "u", methods: ["totp"] }),
  verify2fa: async (_input: Verify2FAInput) => ({ state: "ready", username: "u" }),
  logout: async () => undefined,
};

describe("OneThuCampusAdapter", () => {
  it("maps the Study + Time snapshot into traceable events", async () => {
    const adapter = new OneThuCampusAdapter({ session: fakeSession(), auth });
    const snapshot = await adapter.collectSnapshot();
    expect(snapshot.events.map((event) => event.type)).toEqual([
      "study.course.discovered",
      "study.assignment.discovered",
      "time.schedule.entry",
      "time.academic_calendar.updated",
    ]);
    expect(snapshot.events[1]?.provenance.upstream_id).toBe("assignment:hw-1");
    expect(snapshot.events[1]?.context.course_id).toBe("course-1");
  });

  it("shares one in-flight collection when called twice", async () => {
    const session = fakeSession();
    let homeworkCalls = 0;
    session.learn.getAllHomework = async () => {
      homeworkCalls += 1;
      await new Promise((resolve) => setTimeout(resolve, 10));
      return [];
    };
    const adapter = new OneThuCampusAdapter({ session, auth });
    const [first, second] = await Promise.all([adapter.collectSnapshot(), adapter.collectSnapshot()]);
    expect(homeworkCalls).toBe(1);
    expect(first.events).toEqual(second.events);
  });

  it("uses stable schedule identities and changes assignment version when status changes", () => {
    const fetchedAt = "2026-09-26T10:00:00+08:00";
    const schedule = { courseName: "线性代数", date: "2026-09-28", startSection: 1, endSection: 2, location: "六教" };
    expect(mapScheduleEvent(schedule, fetchedAt).client_event_id)
      .toBe(mapScheduleEvent({ ...schedule }, "2026-09-27T10:00:00+08:00").client_event_id);

    const assignment = {
      id: "hw-1", courseId: "course-1", title: "HW1", content: "完成练习",
      publishTime: "2026-09-26 09:00", deadline: "2026-09-28 23:59",
      submitted: false, graded: false, url: "https://learn.tsinghua.edu.cn/hw-1",
    };
    const discovered = mapAssignmentEvent(assignment, fetchedAt);
    const updated = mapAssignmentEvent({ ...assignment, submitted: true }, fetchedAt);
    expect(discovered.client_event_id).not.toBe(updated.client_event_id);
    expect(updated.type).toBe("study.assignment.updated");
  });
});
