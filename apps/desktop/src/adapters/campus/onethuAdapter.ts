import {
  AuthRequiredError,
  CampusSession,
  type CalendarData,
  type CourseFile,
  type CourseInfo,
  type Homework,
  type ScheduleEntry,
} from "@onethu/core";
import type {
  CampusAdapter,
  CampusAssignment,
  CampusAuthGateway,
  CampusCalendar,
  CampusCourse,
  CampusCourseFile,
  CampusScheduleEntry,
  CampusSnapshot,
  DateRange,
  LoginInput,
  SessionStatus,
  Verify2FAInput,
} from "./types";
import { mapAssignmentEvent, mapCalendarEvent, mapCourseEvent, mapScheduleEvent } from "./events";
import { CampusAuthError } from "./types";

export interface OneThuAdapterOptions {
  session: CampusSession;
  auth: CampusAuthGateway;
}

function requireReady(session: CampusSession): void {
  if (session.state !== "ready") throw new CampusAuthError();
}

async function requireLearnSession(session: CampusSession): Promise<void> {
  if (session.learn.csrfToken) return;
  if (!await session.learn.resume()) {
    throw new CampusAuthError("网络学堂会话未能建立，请重新登录后重试");
  }
}

function mapCourse(course: CourseInfo): CampusCourse {
  return {
    id: course.id,
    name: course.name,
    englishName: course.englishName,
    courseNumber: course.courseNumber,
    teacherName: course.teacherName,
    timeAndLocation: course.timeAndLocation,
    url: course.url,
  };
}

/** vendor CourseFile 原样映射（§5.1：字段口径以 vendor 实测归一化为准，
 *  此处不发明第二套形状）；downloadUrl 保持会话态（见 types.ts 注记）。 */
function mapCourseFile(file: CourseFile): CampusCourseFile {
  return {
    id: file.id,
    courseId: file.courseId,
    title: file.title,
    uploadTime: file.uploadTime,
    downloadUrl: file.downloadUrl,
    fileType: file.fileType,
    size: file.size,
    description: file.description,
    important: file.important,
  };
}

function mapAssignment(assignment: Homework, courseName?: string): CampusAssignment {
  return {
    id: assignment.id,
    courseId: assignment.courseId,
    // vendor 的 courseName 仅外部源（exthw）携带；learn 作业从课程列表映射
    courseName: assignment.courseName ?? courseName,
    title: assignment.title,
    content: assignment.content,
    publishTime: assignment.publishTime,
    deadline: assignment.deadline,
    lateDeadline: assignment.lateDeadline,
    submitted: assignment.submitted,
    graded: assignment.graded,
    url: assignment.url,
  };
}

function mapSchedule(entry: ScheduleEntry): CampusScheduleEntry {
  return {
    courseName: entry.courseName,
    teacher: entry.teacher,
    date: entry.date,
    dayOfWeek: entry.dayOfWeek,
    startSection: entry.startSection,
    endSection: entry.endSection,
    location: entry.location,
    weekText: entry.weekText,
    category: entry.category,
    startTime: entry.startTime,
    endTime: entry.endTime,
  };
}

function mapCalendar(calendar: CalendarData): CampusCalendar {
  return {
    firstDay: calendar.firstDay,
    semesterId: calendar.semesterId,
    semesterName: calendar.semesterName,
    weekCount: calendar.weekCount,
    nextSemesterList: calendar.nextSemesterList,
  };
}

function dateOnly(value: Date): string {
  return value.toISOString().slice(0, 10);
}

const COLLECTION_TIMEOUT_MS = 120_000;

function withTimeout<T>(promise: Promise<T>, milliseconds: number): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<T>((_, reject) => {
    timer = setTimeout(() => reject(new Error("校园数据采集超过 120 秒，请检查网络后重试")), milliseconds);
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

export class OneThuCampusAdapter implements CampusAdapter {
  constructor(private readonly options: OneThuAdapterOptions) {}

  private collectionInFlight: Promise<CampusSnapshot> | undefined;

  async restore(): Promise<SessionStatus> {
    return this.applyStatus(await this.options.auth.restore());
  }

  async login(input: LoginInput): Promise<SessionStatus> {
    return this.applyStatus(await this.options.auth.login(input));
  }

  async send2fa(method: string): Promise<SessionStatus> {
    return this.applyStatus(await this.options.auth.send2fa(method));
  }

  async verify2fa(input: Verify2FAInput): Promise<SessionStatus> {
    return this.applyStatus(await this.options.auth.verify2fa(input));
  }

  canRetryTwoFactor(): boolean {
    return this.options.auth.canRetryTwoFactor();
  }

  async retryTwoFactor(): Promise<SessionStatus | null> {
    const status = await this.options.auth.retryTwoFactor();
    return status === null ? null : this.applyStatus(status);
  }

  async logout(): Promise<void> {
    await this.options.auth.logout();
    this.options.session.reset();
  }

  async getCourses(): Promise<CampusCourse[]> {
    return this.read(async () => {
    const { session } = this.options;
    requireReady(session);
    await requireLearnSession(session);
    const semester = await session.learn.getCurrentSemester();
    return (await session.learn.getCourseList(semester.id)).map(mapCourse);
    });
  }

  /** 课程文件列表（讲解页按需拉取，§2 裁定：不进采集循环）。XSRF 失效
   *  经 read() 的既有重登恢复路径兜底（D8 同源）。 */
  async getCourseFiles(courseId: string): Promise<CampusCourseFile[]> {
    return this.read(async () => {
      const { session } = this.options;
      requireReady(session);
      await requireLearnSession(session);
      return (await session.learn.getFileList(courseId)).map(mapCourseFile);
    });
  }

  async getAssignments(): Promise<CampusAssignment[]> {
    return this.read(async () => {
    const { session } = this.options;
    requireReady(session);
    await requireLearnSession(session);
    const semester = await session.learn.getCurrentSemester();
    const courses = await session.learn.getCourseList(semester.id);
    const courseNames = new Map(courses.map((course) => [course.id, course.name]));
    return (await session.learn.getAllHomework(courses.map((course) => course.id)))
      .map((homework) => mapAssignment(homework, courseNames.get(homework.courseId)));
    });
  }

  async getSchedule(range: DateRange): Promise<CampusScheduleEntry[]> {
    return this.read(async () => {
    const { session } = this.options;
    requireReady(session);
    return (await session.info.getSchedule(range.start, range.end)).map(mapSchedule);
    });
  }

  async getAcademicCalendar(): Promise<CampusCalendar> {
    return this.read(async () => {
    const { session } = this.options;
    requireReady(session);
    await requireLearnSession(session);
    return mapCalendar(await session.learn.getCalendarData());
    });
  }

  async collectSnapshot(): Promise<CampusSnapshot> {
    // Keep collection single-flight. A second click should observe the existing
    // request instead of multiplying the upstream course/homework calls.
    if (!this.collectionInFlight) {
      const operation = this.read(() => this.collectOnce());
      this.collectionInFlight = operation.finally(() => {
        this.collectionInFlight = undefined;
      });
    }
    return withTimeout(this.collectionInFlight, COLLECTION_TIMEOUT_MS);
  }

  private async collectOnce(): Promise<CampusSnapshot> {
    const fetchedAt = new Date().toISOString();
    try {
      const { session } = this.options;
      requireReady(session);
      const now = new Date();
      await requireLearnSession(session);
      const schedulePromise = session.info.getSchedule(
        dateOnly(now), dateOnly(new Date(now.getTime() + 14 * 24 * 60 * 60 * 1000)),
      );
      const learnPromise = (async () => {
        const calendarRaw = await session.learn.getCalendarData();
        const coursesRaw = await session.learn.getCourseList(calendarRaw.semesterId);
        const assignmentsRaw = await session.learn.getAllHomework(coursesRaw.map((course) => course.id));
        return { calendarRaw, coursesRaw, assignmentsRaw };
      })();
      const [scheduleRaw, { calendarRaw, coursesRaw, assignmentsRaw }] = await Promise.all([
        schedulePromise, learnPromise,
      ]);
      const courses = coursesRaw.map(mapCourse);
      const courseNames = new Map(coursesRaw.map((course) => [course.id, course.name]));
      const assignments = assignmentsRaw.map((homework) => mapAssignment(homework, courseNames.get(homework.courseId)));
      const calendar = mapCalendar(calendarRaw);
      const schedule = scheduleRaw.map(mapSchedule);
      return {
        fetchedAt,
        events: [
          ...courses.map((course) => mapCourseEvent(course, fetchedAt)),
          ...assignments.map((assignment) => mapAssignmentEvent(assignment, fetchedAt)),
          ...schedule.map((entry) => mapScheduleEvent(entry, fetchedAt)),
          mapCalendarEvent(calendar, fetchedAt),
        ],
      };
    } catch (error) {
      // 透出上游真实原因（如 XSRF 缺失、漫游失败），不再折叠成通用文案。
      if (error instanceof AuthRequiredError) throw new CampusAuthError(error.message);
      throw error;
    }
  }

  private recovery: Promise<SessionStatus> | undefined;

  private async read<T>(operation: () => Promise<T>): Promise<T> {
    requireReady(this.options.session);
    try {
      return await operation();
    } catch (error) {
      if (!(error instanceof AuthRequiredError || error instanceof CampusAuthError)) throw error;
      this.recovery ??= this.restore().finally(() => { this.recovery = undefined; });
      if ((await this.recovery).state !== "ready") throw new CampusAuthError();
      try {
        return await operation();
      } catch (retryError) {
        if (retryError instanceof AuthRequiredError || retryError instanceof CampusAuthError) {
          this.options.session.reset();
          throw retryError instanceof CampusAuthError ? retryError : new CampusAuthError(retryError.message);
        }
        throw retryError;
      }
    }
  }

  private applyStatus(status: SessionStatus): SessionStatus {
    if (status.state === "ready") {
      this.options.session.state = "ready";
      this.options.session.username = status.username;
    } else if (status.state === "need-2fa") {
      this.options.session.state = "need-2fa";
      this.options.session.username = status.username;
    } else {
      this.options.session.reset();
    }
    return status;
  }
}
