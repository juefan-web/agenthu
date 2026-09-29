import { describe, expect, it } from "vitest";
import { formatAvailableMinutes } from "./format";

describe("formatAvailableMinutes", () => {
  it("formats hour-plus remainders compactly", () => {
    expect(formatAvailableMinutes(200)).toBe("3h20m");
    expect(formatAvailableMinutes(60)).toBe("1h");
    expect(formatAvailableMinutes(125)).toBe("2h5m");
  });

  it("keeps sub-hour values in minutes", () => {
    expect(formatAvailableMinutes(45)).toBe("45m");
    expect(formatAvailableMinutes(0)).toBe("0m");
  });

  it("clamps and rounds hostile inputs for display", () => {
    expect(formatAvailableMinutes(-5)).toBe("0m");
    expect(formatAvailableMinutes(59.6)).toBe("1h");
  });
});
