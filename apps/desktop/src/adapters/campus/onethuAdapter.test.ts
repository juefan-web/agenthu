import { describe, expect, it } from "vitest";
import { AuthRequiredError, type CampusSession } from "@onethu/core";
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
  canRetryTwoFactor: () => false,
  retryTwoFactor: async () => null,
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
    // courseName 经课程列表映射进入事件 data（L3 派生标题的输入）
    expect(snapshot.events[1]?.data.course_name).toBe("线性代数");
  });

  it("maps the course name from the course list onto assignments (L3)", async () => {
    const session = fakeSession();
    // course-2 不在课程列表里：映射缺失时应得到 null 而不是误配
    session.learn.getAllHomework = async () => [
      {
        id: "hw-1",
        courseId: "course-1",
        title: "HW1",
        content: "",
        publishTime: "2026-09-26 09:00",
        deadline: "2026-09-28 23:59",
        submitted: false,
        graded: false,
        url: "https://learn.tsinghua.edu.cn/hw-1",
      },
      {
        id: "hw-orphan",
        courseId: "course-2",
        title: "HW2",
        content: "",
        publishTime: "2026-09-26 09:00",
        deadline: "2026-09-28 23:59",
        submitted: false,
        graded: false,
        url: "https://learn.tsinghua.edu.cn/hw-orphan",
      },
    ];
    const adapter = new OneThuCampusAdapter({ session, auth });
    const assignments = await adapter.getAssignments();
    expect(assignments.map((item) => item.courseName)).toEqual(["线性代数", undefined]);
  });

  it("counts partial homework failures instead of swallowing them (external #14)", async () => {
    const session = fakeSession();
    // 单项失败仍返回部分结果（vendored 语义），失败经回调计数透出
    session.learn.getAllHomework = async (courseIds, onPartialFailure) => {
      onPartialFailure?.({ courseId: courseIds[0]!, kind: "new" });
      onPartialFailure?.({ courseId: courseIds[0]!, kind: "graded" });
      return [];
    };
    const snapshot = await new OneThuCampusAdapter({ session, auth }).collectSnapshot();
    expect(snapshot.partial).toEqual({ failedQueries: 2, totalQueries: 3 });
  });

  it("omits the partial marker when every homework query succeeds", async () => {
    const snapshot = await new OneThuCampusAdapter({ session: fakeSession(), auth }).collectSnapshot();
    expect(snapshot.partial).toBeUndefined();
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

  it("uses the calendar semester and starts schedule collection before homework completes", async () => {
    const session = fakeSession();
    let requestedSemester = "";
    let scheduleCalls = 0;
    let finishHomework!: () => void;
    let homeworkStarted!: () => void;
    const homeworkGate = new Promise<void>((resolve) => { finishHomework = resolve; });
    const started = new Promise<void>((resolve) => { homeworkStarted = resolve; });
    session.learn.getCurrentSemester = async () => { throw new Error("redundant semester request"); };
    session.learn.getCourseList = async (semesterId) => {
      requestedSemester = semesterId;
      return [];
    };
    session.learn.getAllHomework = async () => {
      homeworkStarted();
      await homeworkGate;
      return [];
    };
    session.info.getSchedule = async () => { scheduleCalls += 1; return []; };

    const collection = new OneThuCampusAdapter({ session, auth }).collectSnapshot();
    await started;
    expect(requestedSemester).toBe("2026-2027-1");
    expect(scheduleCalls).toBe(1);
    finishHomework();
    await collection;
  });

  it("surfaces the underlying auth error message instead of a generic one", async () => {
    const session = fakeSession();
    session.info.getSchedule = async () => {
      throw new AuthRequiredError("XSRF-TOKEN 缺失（wengine dance 后仍无）");
    };
    const adapter = new OneThuCampusAdapter({ session, auth });
    await expect(adapter.collectSnapshot()).rejects.toThrow("XSRF-TOKEN 缺失（wengine dance 后仍无）");
  });

  it("maps course files verbatim from the vendor shape (downloadUrl stays session-state)", async () => {
    const session = fakeSession();
    session.learn.getFileList = async (courseId: string) => [{
      id: "wjid-1",
      courseId,
      title: "第3讲 傅里叶变换.pdf",
      uploadTime: "2026-09-26 10:00",
      downloadUrl: "https://learn.tsinghua.edu.cn/b/download?wjid=wjid-1",
      fileType: "pdf",
      size: "2.3MB",
      description: "课件",
      important: true,
    }];
    const files = await new OneThuCampusAdapter({ session, auth }).getCourseFiles("course-1");
    expect(files).toEqual([{
      id: "wjid-1",
      courseId: "course-1",
      title: "第3讲 傅里叶变换.pdf",
      uploadTime: "2026-09-26 10:00",
      downloadUrl: "https://learn.tsinghua.edu.cn/b/download?wjid=wjid-1",
      fileType: "pdf",
      size: "2.3MB",
      description: "课件",
      important: true,
    }]);
  });

  it("recovers a stale learn session once while listing course files (D8 path)", async () => {
    const session = fakeSession();
    let calls = 0;
    session.learn.getFileList = async () => {
      calls += 1;
      if (calls === 1) throw new AuthRequiredError("learn 会话过期");
      return [];
    };
    const files = await new OneThuCampusAdapter({ session, auth }).getCourseFiles("course-1");
    expect(files).toEqual([]);
    expect(calls).toBe(2); // read() 恢复路径重试了一次
  });

  it("propagates a non-auth listing failure untouched (no silent empty list)", async () => {
    const session = fakeSession();
    session.learn.getFileList = async () => {
      throw new Error("learn 文件列表接口 500");
    };
    await expect(new OneThuCampusAdapter({ session, auth }).getCourseFiles("course-1"))
      .rejects.toThrow("learn 文件列表接口 500");
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
