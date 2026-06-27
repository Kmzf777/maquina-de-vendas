import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { debounce } from "@/lib/debounce";

describe("debounce", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("colapsa múltiplas chamadas em uma só após o intervalo", () => {
    const fn = vi.fn();
    const d = debounce(fn, 1000);
    d(); d(); d();
    expect(fn).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1000);
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it("cancel() impede a execução pendente", () => {
    const fn = vi.fn();
    const d = debounce(fn, 1000);
    d();
    d.cancel();
    vi.advanceTimersByTime(1000);
    expect(fn).not.toHaveBeenCalled();
  });
});
