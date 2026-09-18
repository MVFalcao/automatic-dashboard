import { describe, expect, it } from "vitest";
import { isAbsoluteLocalPath, problemMessage } from "./DashboardReview";

describe("problemMessage", () => {
  it("returns the fallback when problem is not an object", () => {
    expect(problemMessage(null, "fallback")).toBe("fallback");
    expect(problemMessage("oops", "fallback")).toBe("fallback");
  });

  it("returns a plain string detail as-is", () => {
    expect(problemMessage({ detail: "Something broke" }, "fallback")).toBe("Something broke");
  });

  it("joins structured field errors", () => {
    const problem = { detail: { fields: [{ field: "goal", message: "is required" }, { message: "second issue" }] } };
    expect(problemMessage(problem, "fallback")).toBe("goal: is required · request: second issue");
  });

  it("falls back to the structured message when there are no fields", () => {
    expect(problemMessage({ detail: { message: "structured message" } }, "fallback")).toBe("structured message");
  });

  it("joins a list of validation error objects", () => {
    const problem = { detail: [{ msg: "bad value" }, "not an object"] };
    expect(problemMessage(problem, "fallback")).toBe("bad value · fallback");
  });

  it("falls back when detail is missing entirely", () => {
    expect(problemMessage({}, "fallback")).toBe("fallback");
  });
});

describe("isAbsoluteLocalPath", () => {
  it("accepts a Windows absolute path", () => {
    expect(isAbsoluteLocalPath("C:\\Users\\Name\\Documents\\DashboardProject")).toBe(true);
  });

  it("accepts a POSIX absolute path", () => {
    expect(isAbsoluteLocalPath("/home/name/DashboardProject")).toBe(true);
  });

  it("accepts a UNC path", () => {
    expect(isAbsoluteLocalPath("\\\\server\\share\\DashboardProject")).toBe(true);
  });

  it("rejects a relative path", () => {
    expect(isAbsoluteLocalPath("relative/path")).toBe(false);
  });

  it("rejects an http(s) URL even if it looks path-like", () => {
    expect(isAbsoluteLocalPath("https://example.com/DashboardProject")).toBe(false);
  });

  it("trims surrounding whitespace before checking", () => {
    expect(isAbsoluteLocalPath("  /home/name/DashboardProject  ")).toBe(true);
  });
});
