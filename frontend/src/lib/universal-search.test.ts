import { describe, it, expect } from "vitest";
import { parseSearchParams, limitForTab, offsetFor, startOfDayIso, endOfDayIso } from "./universal-search";

describe("parseSearchParams", () => {
  it("defaults to tab=all and page=1 when absent", () => {
    const parsed = parseSearchParams(new URLSearchParams("q=jose"));
    expect(parsed).toEqual({
      q: "jose", tab: "all", dateFrom: null, dateTo: null,
      pipelineId: null, stageId: null, leadStage: null, docsOnly: false, page: 1,
    });
  });

  it("trims q and falls back to 'all' for an invalid tab", () => {
    const parsed = parseSearchParams(new URLSearchParams("q= jose &tab=bogus"));
    expect(parsed.q).toBe("jose");
    expect(parsed.tab).toBe("all");
  });

  it("parses every optional filter", () => {
    const parsed = parseSearchParams(
      new URLSearchParams(
        "q=x&tab=deals&date_from=2026-01-01&date_to=2026-01-31&pipeline_id=p1&stage_id=s1&lead_stage=atacado&docs_only=true&page=3"
      )
    );
    expect(parsed).toEqual({
      q: "x", tab: "deals", dateFrom: "2026-01-01", dateTo: "2026-01-31",
      pipelineId: "p1", stageId: "s1", leadStage: "atacado", docsOnly: true, page: 3,
    });
  });

  it("clamps page to at least 1", () => {
    expect(parseSearchParams(new URLSearchParams("q=x&page=0")).page).toBe(1);
    expect(parseSearchParams(new URLSearchParams("q=x&page=-5")).page).toBe(1);
    expect(parseSearchParams(new URLSearchParams("q=x&page=abc")).page).toBe(1);
  });
});

describe("limitForTab", () => {
  it("returns 5 for the 'all' preview tab", () => {
    expect(limitForTab("all")).toBe(5);
  });
  it("returns 20 for a specific tab", () => {
    expect(limitForTab("leads")).toBe(20);
    expect(limitForTab("deals")).toBe(20);
    expect(limitForTab("sales")).toBe(20);
    expect(limitForTab("conversations")).toBe(20);
  });
});

describe("offsetFor", () => {
  it("computes 0-indexed Postgres OFFSET from a 1-indexed page", () => {
    expect(offsetFor(1, 20)).toBe(0);
    expect(offsetFor(2, 20)).toBe(20);
    expect(offsetFor(3, 5)).toBe(10);
  });
  it("never returns negative", () => {
    expect(offsetFor(0, 20)).toBe(0);
  });
});

describe("startOfDayIso / endOfDayIso", () => {
  it("expands a yyyy-mm-dd date to UTC start/end of day", () => {
    expect(startOfDayIso("2026-08-18")).toBe("2026-08-18T00:00:00.000Z");
    expect(endOfDayIso("2026-08-18")).toBe("2026-08-18T23:59:59.999Z");
  });
  it("passes through an already-full ISO timestamp unchanged", () => {
    expect(startOfDayIso("2026-08-18T10:00:00.000Z")).toBe("2026-08-18T10:00:00.000Z");
  });
});
