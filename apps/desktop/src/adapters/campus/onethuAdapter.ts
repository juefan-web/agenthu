import {
  AuthRequiredError,
  CampusSession,
  type CalendarData,
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

function mapAssignment(assignment: Homework): CampusAssignment {
  return {
    id: assignment.id,
    courseId: assignment.courseId,
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

export class OneThuCampusAdapter implements CampusAdapter {
  constructor(private readonly options: OneThuAdapterOptions) {}

  async restore(): Promise<SessionStatus> {
    return this.applyStatus(await this.options.auth.restore());
  }

  async login(input: LoginInput): Promise<SessionStatus> {
    const status = await this.options.auth.login(input);
    if (status.state === "ready" || status.state === "need-2fa") {
      this.options.session.injectCredentials(input.username, input.password);
    }
    return this.applyStatus(status);
  }

  async verify2fa(input: Verify2FAInput): Promise<SessionStatus> {
    return this.applyStatus(await this.options.auth.verify2fa(input));
  }

  async logout(): Promise<void> {
    await this.options.auth.logout();
    this.options.session.reset();
  }

  async getCourses(): Promise<CampusCourse[]> {
    const { session } = this.options;
    requireReady(session);
    const semester = await session.learn.getCurrentSemester();
    return (await session.learn.getCourseList(semester.id)).map(mapCourse);
  }

  async getAssignments(): Promise<CampusAssignment[]> {
    const { session } = this.options;
    requireReady(session);
    const semester = await session.learn.getCurrentSemester();
    const courses = await session.learn.getCourseList(semester.id);
    return (await session.learn.getAllHomework(courses.map((course) => course.id))).map(mapAssignment);
  }

  async getSchedule(range: DateRange): Promise<CampusScheduleEntry[]> {
    const { session } = this.options;
    requireReady(session);
    return (await session.info.getSchedule(range.start, range.end)).map(mapSchedule);
  }

  async getAcademicCalendar(): Promise<CampusCalendar> {
    const { session } = this.options;
    requireReady(session);
    return mapCalendar(await session.learn.getCalendarData());
  }

  async collectSnapshot(): Promise<CampusSnapshot> {
    const fetchedAt = new Date().toISOString();
    try {
      requireReady(this.options.session);
      const semester = await this.options.session.learn.getCurrentSemester();
      const [coursesRaw, calendarRaw] = await Promise.all([
        this.options.session.learn.getCourseList(semester.id),
        this.options.session.learn.getCalendarData(),
      ]);
      const assignmentsRaw = await this.options.session.learn.getAllHomework(
        coursesRaw.map((course) => course.id),
      );
      const now = new Date();
      const scheduleRaw = await this.options.session.info.getSchedule(
        dateOnly(now),
        dateOnly(new Date(now.getTime() + 14 * 24 * 60 * 60 * 1000)),
      );
      const courses = coursesRaw.map(mapCourse);
      const assignments = assignmentsRaw.map(mapAssignment);
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
      if (error instanceof AuthRequiredError) throw new CampusAuthError();
      throw error;
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
