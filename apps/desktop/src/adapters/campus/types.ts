import type { EventEnvelope } from "@agenthu/contracts";

export type SessionStatus =
  | { state: "idle"; username: null }
  | { state: "need-2fa"; username: string; methods: string[]; codeSent?: boolean; selectedMethod?: string; notice?: string }
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

/** 课程课件（learn 域 getFileList，TASKS/m3-materials-upload-ui.md §3.1）：
 *  按需拉取的会话态数据——不进采集循环、不落任何 Event（§2 裁定）。 */
export interface CampusCourseFile {
  id: string;
  courseId: string;
  title: string;
  uploadTime: string;
  /** 会话态下载 URL：仅作当次上传命令的入参，不进 Event/本地存储/同步
   *  队列（D-033：downloadUrl 不入 Event）。 */
  downloadUrl: string;
  fileType?: string;
  /** 人类可读大小（vendor 原样，如 "2.3MB"）。 */
  size?: string;
  description?: string;
  important?: boolean;
}

export interface CampusAssignment {
  id: string;
  courseId: string;
  /** 课程名（L3）：learn 作业从课程列表映射（vendor Homework 不携带），
   *  外部源（DSA 等）透传 vendor 的 courseName；未知为 undefined */
  courseName?: string;
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

/** 采集部分失败计数（外审 #14）：单项查询失败时采集仍产出部分结果，
 *  失败事实不得被 catch(()=>[]) 吞掉。仅计数——错误详情留在 debug 通道，
 *  不进 Event 载荷与 UI。 */
export interface CampusCollectionPartial {
  failedQueries: number;
  totalQueries: number;
}

export interface CampusSnapshot {
  fetchedAt: string;
  events: EventEnvelope[];
  /** 仅在本轮存在失败查询时在场；缺省 = 完整采集 */
  partial?: CampusCollectionPartial;
}

export interface CampusAuthGateway {
  restore(): Promise<SessionStatus>;
  login(input: LoginInput): Promise<SessionStatus>;
  send2fa(method: string): Promise<SessionStatus>;
  verify2fa(input: Verify2FAInput): Promise<SessionStatus>;
  /** 错误态原地重试是否可用（凭据仍在内存）。 */
  canRetryTwoFactor(): boolean;
  /** 错误态「重试验证」：重启整链回 2FA 表单或直接就绪；凭据已清返回 null。 */
  retryTwoFactor(): Promise<SessionStatus | null>;
  logout(): Promise<void>;
}

export interface CampusAdapter {
  restore(): Promise<SessionStatus>;
  login(input: LoginInput): Promise<SessionStatus>;
  send2fa(method: string): Promise<SessionStatus>;
  verify2fa(input: Verify2FAInput): Promise<SessionStatus>;
  canRetryTwoFactor(): boolean;
  retryTwoFactor(): Promise<SessionStatus | null>;
  logout(): Promise<void>;
  getCourses(): Promise<CampusCourse[]>;
  getCourseFiles(courseId: string): Promise<CampusCourseFile[]>;
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
