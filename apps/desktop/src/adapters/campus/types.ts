import type { EventEnvelope } from "@agenthu/contracts";

export type SessionStatus =
  | { state: "idle"; username: null }
  | { state: "need-2fa"; username: string; methods: string[]; codeSent?: boolean; selectedMethod?: string }
  | { state: "ready"; username: string }
  | { state: "error"; username: string | null; message: string };

export interface LoginInput {
  username: string;
  password: string;
}

export interface Verify2FAInput {
  method: string;
  code: string;
  trustDevice: boolean;
}

export interface DateRange {
  start: string;
  end: string;
}

export interface CampusCourse {
  id: string;
  name: string;
  englishName: string;
  courseNumber: string;
  teacherName: string;
  timeAndLocation: string[];
  url: string;
}

export interface CampusAssignment {
  id: string;
  courseId: string;
  title: string;
  content: string;
  publishTime: string;
  deadline: string;
  lateDeadline?: string;
  submitted: boolean;
  graded: boolean;
  url: string;
}

export interface CampusScheduleEntry {
  courseName: string;
  teacher?: string;
  date?: string;
  dayOfWeek?: number;
  startSection?: number;
  endSection?: number;
  location?: string;
  weekText?: string;
  category?: string;
  startTime?: string;
  endTime?: string;
}

export interface CampusCalendar {
  firstDay: string;
  semesterId: string;
  semesterName: string;
  weekCount: number;
  nextSemesterList: Array<{
    firstDay: string;
    semesterId: string;
    semesterName: string;
    weekCount: number;
  }>;
}

export interface CampusSnapshot {
  fetchedAt: string;
  events: EventEnvelope[];
}

export interface CampusAuthGateway {
  restore(): Promise<SessionStatus>;
  login(input: LoginInput): Promise<SessionStatus>;
  send2fa(method: string): Promise<SessionStatus>;
  verify2fa(input: Verify2FAInput): Promise<SessionStatus>;
  logout(): Promise<void>;
}

export interface CampusAdapter {
  restore(): Promise<SessionStatus>;
  login(input: LoginInput): Promise<SessionStatus>;
  send2fa(method: string): Promise<SessionStatus>;
  verify2fa(input: Verify2FAInput): Promise<SessionStatus>;
  logout(): Promise<void>;
  getCourses(): Promise<CampusCourse[]>;
  getAssignments(): Promise<CampusAssignment[]>;
  getSchedule(range: DateRange): Promise<CampusScheduleEntry[]>;
  getAcademicCalendar(): Promise<CampusCalendar>;
  collectSnapshot(): Promise<CampusSnapshot>;
}

export class CampusAuthError extends Error {
  constructor(message = "校园会话已失效，请重新登录") {
    super(message);
    this.name = "CampusAuthError";
  }
}
