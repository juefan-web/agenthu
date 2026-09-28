/**
 * 脱敏层 —— 把「能指认到具体人」的字段换成化名 / 编造值，其余数据原样保留。
 *
 * 设计约束（与用户需求一一对应）：
 *  1) 登录与正式版完全相同（真实清华 ID + 2FA），脱敏只发生在数据进入界面之前；
 *  2) 姓名（自己 / 老师 / 助教 / 讨论区发帖与回复 / 分组同学 / 通知发布人 / 校园卡 /
 *     发票 / 网络账号 / 体测与体育预约）与学号一律替换为化名与编造学号；
 *  3) 成绩（成绩单、作业与考试得分、雨课堂）按 GRADE_SCALE 编造 —— 等级与绩点同表，
 *     不出现「A+ 配 3.0」这种不可能组合；
 *  4) 非敏感数据（课程名、课表、教室、洗衣机、图书馆座位、新闻…）一律照旧，不做任何改写；
 *  5) 已见过的真实姓名会被记进映射表，随后出现在**富文本正文**里的同名文本（讨论区帖子正文、
 *     通知正文、评语）也会被替换 —— 结构化字段之外的口径也覆盖。
 *
 * 默认关闭（见 config.ts）：正式分支此模块为纯函数库，不被调用。
 */
import { DESENSITIZE_ENABLED } from "./config.js";

/* ───────────────────────── 化名与学号 ───────────────────────── */

/** 化名池：张三李四一类的通用名，不指向任何真实的人。 */
export const PSEUDO_NAMES: readonly string[] = [
  "张三", "李四", "王五", "赵六", "钱七", "孙八", "周九", "吴十",
  "郑一", "王小明", "李华", "张伟", "王芳", "李娜", "刘洋", "陈静",
  "杨帆", "黄磊", "徐蕾", "赵敏", "林川", "何静", "高远", "罗雨",
];

/** 真实姓名 → 化名（同一进程内稳定；不同姓名尽量不撞同一个化名）。 */
const nameMap = new Map<string, string>();
/** 化名 → 真实姓名（用于判断化名是否已被占用）。 */
const usedPseudo = new Set<string>();

function hash32(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

/** 姓名 → 化名：稳定、确定性（同一个人每次都是同一个化名），空串原样返回。 */
export function maskName(real: string): string {
  const key = real.trim();
  if (!key) return "";
  const hit = nameMap.get(key);
  if (hit) return hit;
  const start = hash32(key) % PSEUDO_NAMES.length;
  let pick = "";
  for (let i = 0; i < PSEUDO_NAMES.length; i++) {
    const cand = PSEUDO_NAMES[(start + i) % PSEUDO_NAMES.length]!;
    if (!usedPseudo.has(cand)) {
      pick = cand;
      break;
    }
  }
  if (!pick) pick = `${PSEUDO_NAMES[start]!}${(hash32(key) % 90) + 10}`; // 池子用尽才带序号
  nameMap.set(key, pick);
  usedPseudo.add(pick);
  return pick;
}

/** 学号 → 编造学号：保留年级前缀（10 位学号的前 4 位），其余按哈希生成。 */
export function maskStudentId(real: string): string {
  const key = real.trim();
  if (!key) return "";
  const digits = (hash32(key) % 900000 + 100000).toString();
  if (/^\d{10}$/.test(key)) return `${key.slice(0, 4)}${digits}`;
  if (/^\d{4,}$/.test(key)) return `${key.slice(0, 4)}${digits}`;
  return key.replace(/\d/g, (d) => String((Number(d) + 3) % 10)); // 非纯数字（如邮箱前缀）只做数字扰动
}

/** 已记录的真实姓名（供富文本正文替换使用）。 */
export function knownNameMappings(): ReadonlyMap<string, string> {
  return nameMap;
}

/** 清空映射（测试与「重新登录」时使用）。 */
export function resetPseudoMappings(): void {
  nameMap.clear();
  usedPseudo.clear();
}

/* ───────────────────────── 成绩 ───────────────────────── */

/**
 * 清华成绩等级 → 学分绩点（A+/A/A- = 4.0，B+ = 3.6，B = 3.3，B- = 3.0，
 * 其后依次 C+/C/C- = 2.6/2.3/2.0、D+/D = 1.6/1.3、F = 0）。
 * 编造成绩时**等级与绩点必须取自同一行**。
 */
export const GRADE_SCALE: ReadonlyArray<{ grade: string; point: number }> = [
  { grade: "A+", point: 4.0 },
  { grade: "A", point: 4.0 },
  { grade: "A-", point: 4.0 },
  { grade: "B+", point: 3.6 },
  { grade: "B", point: 3.3 },
  { grade: "B-", point: 3.0 },
  { grade: "C+", point: 2.6 },
  { grade: "C", point: 2.3 },
  { grade: "C-", point: 2.0 },
  { grade: "D+", point: 1.6 },
  { grade: "D", point: 1.3 },
  { grade: "F", point: 0 },
];

/**
 * 编造只用**高分段**：A+/A/A-（4.0）与 B+（3.6）。
 * 抽取池刻意不含 C/D/F —— 真实成绩单里几乎不存在 1.3 这种绩点，
 * 演示时出现「军事理论 1.3」会一眼假（用户实录反馈）。
 */
const FAKE_GRADE_TIERS: ReadonlyArray<{ grade: string; weight: number }> = [
  { grade: "A+", weight: 2 },
  { grade: "A", weight: 4 },
  { grade: "A-", weight: 4 },
  { grade: "B+", weight: 5 },
];

/** 生成一条编造成绩（只出 4.0 与 3.6 档；等级与绩点取自 GRADE_SCALE 同一行）。 */
export function fakeGrade(key: string): { grade: string; point: number } {
  const h = hash32(`grade:${key}`);
  const total = FAKE_GRADE_TIERS.reduce((a, t) => a + t.weight, 0);
  let acc = ((h % 100000) / 100000) * total;
  let picked = FAKE_GRADE_TIERS[FAKE_GRADE_TIERS.length - 1]!;
  for (const tier of FAKE_GRADE_TIERS) {
    acc -= tier.weight;
    if (acc <= 0) {
      picked = tier;
      break;
    }
  }
  const row = GRADE_SCALE.find((g) => g.grade === picked.grade)!;
  return { grade: row.grade, point: row.point };
}

/** 编造百分制得分：按满分折算到 78%–98%，确定性。 */
export function fakeScore(key: string, full = 100): number {
  const base = full > 0 ? full : 100;
  const ratio = 0.78 + ((hash32(`score:${key}`) % 21) / 100);
  return Math.round(base * ratio);
}


/** 编造联系方式：邮箱 → 示例域邮箱；电话 / 手机 → 编造号码（一定与原值不同）。 */
export function fakeContact(key: string, value: string, seed: string): string {
  if (!value.trim()) return value;
  const h = hash32(`${seed}:${key}:${value}`);
  if (key.toLowerCase().includes("email")) {
    return `demo${(h % 9000) + 1000}@example.com`;
  }
  const digits = String(h % 90000000 + 10000000);
  if (value.replace(/\D/g, "").length >= 11) return `138${digits}`.slice(0, 11);
  if (value.replace(/\D/g, "").length >= 7) return `6278${digits.slice(0, 4)}`;
  return value.replace(/[0-9]/g, (d) => String((Number(d) + 5) % 10));
}

/* ───────────────────────── 正文文本替换 ───────────────────────── */

/** 把已记录的真实姓名（以及 10 位学号）从富文本正文里替换掉。 */
export function maskText(text: string): string {
  if (!text) return text;
  let out = text;
  const pairs = [...nameMap.entries()].sort((a, b) => b[0].length - a[0].length);
  for (const [real, pseudo] of pairs) {
    if (real.length >= 2 && out.includes(real)) out = out.split(real).join(pseudo);
  }
  return out.replace(/\b(\d{10})\b/g, (m) => maskStudentId(m));
}

/* ───────────────────────── 通用遍历脱敏 ───────────────────────── */

/** 始终替换为化名的键（这些键在任何结构里都只承载个人姓名 / 身份）。 */
const ALWAYS_NAME_KEYS = new Set([
  "author", "creator", "publisher", "teacherName", "graderName", "teacher",
  "realName", "userName", "cust_name", "assessor", "inspector", "operator",
]);
/** 始终替换为编造学号 / 账号的键。 */
const ALWAYS_ID_KEYS = new Set([
  "sid", "studentId", "username", "userId", "cardId",
  "cust_ts_cardno", "cust_tax_no",
]);
/** 始终替换为编造联系方式的键。 */
const ALWAYS_CONTACT_KEYS = new Set([
  "cust_email", "cust_mob", "contactEmail", "contactPhone", "contactLandline", "email", "phone",
]);
/** 承载富文本 / 自由文本的键：做已知姓名替换，不做结构化改写。 */
const TEXT_KEYS = new Set([
  "html", "content", "description", "gradeContent", "submittedContent", "suggestion",
  "inv_note", "title", "comment", "remark", "note",
]);
/** 父键位于这些容器下的 `name` 一律视为个人姓名（分组同学 / 评教教师与助教）。 */
const PERSONAL_PARENT_KEYS = new Set(["members", "teachers", "assistants"]);


/** 键值对数组（如体测结果 Array<[string, string]>）里的 PII 标签。 */
const TUPLE_NAME_LABELS = new Set(["姓名", "学生姓名", "考生姓名", "名字"]);
const TUPLE_ID_LABELS = new Set(["学号", "账号", "证件号", "身份证号", "一卡通号", "借书证号"]);
const TUPLE_SCORE_HINT = /(得分|成绩|总分|分数)$/;

/** 处理 [标签, 值] 两元组：返回替换后的值，非 PII 返回 undefined。 */
function maskTuple(label: string, value: string, seed: string): string | undefined {
  const key = label.trim();
  if (TUPLE_NAME_LABELS.has(key)) return maskName(value);
  if (TUPLE_ID_LABELS.has(key)) return maskStudentId(value);
  if (TUPLE_SCORE_HINT.test(key)) {
    const n = Number(value);
    if (Number.isFinite(n) && n > 0) return String(fakeScore(seed, n > 0 && n <= 1 ? 1 : 100));
    return value;
  }
  return undefined;
}

function isPlainObject(v: unknown): v is Record<string, unknown> {
  if (v === null || typeof v !== "object") return false;
  const proto = Object.getPrototypeOf(v) as object | null;
  return proto === Object.prototype || proto === null;
}

/** 对象自身形态是否说明它的 `name` 是个人姓名（而非课程名 / 楼名 / 设备名）。 */
function nameLooksPersonal(o: Record<string, unknown>): boolean {
  return (
    "sid" in o || "role" in o || "inputGroups" in o || "gymId" in o ||
    "bookTimestamp" in o || "balance" in o || "cardId" in o || "studentId" in o ||
    "allowedDevices" in o || "userGroup" in o
  );
}

/** 是否为成绩单行（有学分 + 学期 + 等级）。 */
function isReportRow(o: Record<string, unknown>): boolean {
  return typeof o.credit === "number" && typeof o.semester === "string" && "grade" in o;
}

/** 是否为「有得分」的作业 / 考试（等级、得分、评语都要编造）。 */
function isGradedWork(o: Record<string, unknown>): boolean {
  return "graded" in o || ("score" in o && "totalScore" in o) || "myScore" in o;
}

function maskScalarKey(key: string, value: unknown, seed: string): unknown {
  if (typeof value === "string") {
    if (ALWAYS_NAME_KEYS.has(key)) return maskName(value);
    if (ALWAYS_ID_KEYS.has(key)) return key === "username" ? maskStudentId(value) : maskStudentId(value);
    if (ALWAYS_CONTACT_KEYS.has(key)) return fakeContact(key, value, `${seed}`);
    if (TEXT_KEYS.has(key)) return maskText(value);
  }
  if (typeof value === "number" && (key === "score" || key === "totalScore" || key === "myScore")) {
    return fakeScore(seed, value > 0 ? value : 100);
  }
  return undefined;
}

/** 就地（返回新对象）脱敏一个值；数组 / 普通对象递归处理，其余原样返回。 */
export function applyDesensitize<T>(value: T, seed = ""): T {
  return walk(value, seed, "") as T;
}

function walk(value: unknown, seed: string, parentKey: string): unknown {
  if (Array.isArray(value)) {
    if (value.length === 2 && typeof value[0] === "string" && typeof value[1] === "string") {
      const replaced = maskTuple(value[0], value[1], `${seed}#0`);
      if (replaced !== undefined) return [value[0], replaced];
    }
    return value.map((v, i) => walk(v, `${seed}#${i}`, parentKey));
  }
  if (!isPlainObject(value)) return value;

  const report = isReportRow(value);
  const reportSeed = `${seed}:report`;
  const graded = isGradedWork(value);
  const personalName = nameLooksPersonal(value) || PERSONAL_PARENT_KEYS.has(parentKey);
  const out: Record<string, unknown> = {};

  for (const [key, raw] of Object.entries(value)) {
    const keySeed = `${seed}.${key}`;
    // 1) 结构化姓名 / 学号 / 联系方式
    const masked = maskScalarKey(key, raw, keySeed);
    if (masked !== undefined) {
      out[key] = masked;
      continue;
    }
    // 2) 人员引用（研讨间成员搜索结果：label = 学号）
    if (key === "label" && typeof raw === "string" && "department" in value) {
      out[key] = maskStudentId(raw);
      continue;
    }
    // 3) 个人语境下的 name
    if (key === "name" && personalName && typeof raw === "string") {
      out[key] = maskName(raw);
      continue;
    }
    // 4) 成绩单行：等级与绩点同表编造
    if (report && key === "grade" && typeof raw === "string") {
      out[key] = fakeGrade(reportSeed).grade; // 同一行 grade 与 point 共用种子 → 一定同表
      continue;
    }
    if (report && key === "point" && typeof raw === "number") {
      out[key] = fakeGrade(reportSeed).point;
      continue;
    }
    // 5) 作业 / 考试的等级与得分
    if (graded && key === "grade" && (typeof raw === "string" || typeof raw === "number")) {
      const g = fakeGrade(keySeed);
      out[key] = typeof raw === "number" ? g.point : g.grade;
      continue;
    }
    out[key] = walk(raw, keySeed, key);
  }
  return out;
}

/* ───────────────────────── 对外入口 ───────────────────────── */

/**
 * 脱敏入口：正式分支（DESENSITIZE_ENABLED=false）直接原样返回，零开销；
 * demo 分支对**所有**返回数据生效（learn / info / 外部作业源 / 状态层 user 都走这里）。
 */
export function desensitizeTree<T>(value: T, seed = ""): T {
  if (!DESENSITIZE_ENABLED) return value;
  return applyDesensitize(value, seed);
}

/** 供界面角标使用：当前构建是否脱敏版。 */
export function isDesensitizeBuild(): boolean {
  return DESENSITIZE_ENABLED;
}

/** 编造分数只会出现的档位（供测试与界面说明引用）。 */
export const FAKE_GRADE_POOL: ReadonlyArray<string> = FAKE_GRADE_TIERS.map((t) => t.grade);
