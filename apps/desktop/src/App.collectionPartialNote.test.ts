import { describe, expect, it } from "vitest";
import { collectionPartialNote } from "./App";

/** 外审 #14 的 UI 面钉子：部分失败只透出计数（「无作业」与「拉取失败」
 *  之别用户可见），错误详情不进 notice。 */
describe("collectionPartialNote", () => {
  it("renders the failure count over the fan-out total", () => {
    expect(collectionPartialNote({ failedQueries: 2, totalQueries: 9 })).toBe(
      "，作业查询部分失败 2/9",
    );
  });

  it("stays silent for a complete collection", () => {
    expect(collectionPartialNote(undefined)).toBe("");
  });
});
