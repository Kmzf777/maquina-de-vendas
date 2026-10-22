/**
 * @vitest-environment jsdom
 */
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { KpiCard } from "./kpi-card";

afterEach(cleanup);

describe("KpiCard hint (b67f1c6b)", () => {
  it("mostra o ícone 'i' com o texto no title e no aria-label", () => {
    render(<KpiCard label="Leads novos" value={439} hint="explicação do número" />);
    const tip = screen.getByLabelText("explicação do número");
    expect(tip.getAttribute("title")).toBe("explicação do número");
    expect(tip.querySelector("svg")).not.toBeNull();
  });

  it("sem hint não mostra ícone de ajuda", () => {
    const { container } = render(<KpiCard label="Leads novos" value={439} />);
    expect(container.querySelector("[title]")).toBeNull();
  });
});
