/**
 * @vitest-environment jsdom
 */
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render } from "@testing-library/react";
import { ConversionFunnel } from "./conversion-funnel";
import type { DashboardConversion } from "./types";

afterEach(cleanup);

const AJUDA_GANHO =
  "oportunidades marcadas como ganhas no funil. Vendas do Bling sem oportunidade não entram aqui; veja a receita no Painel de vendas.";

describe("ConversionFunnel (D7)", () => {
  it("o 'Ganho' explica que conta oportunidades, não vendas do Bling", () => {
    const data = { leads_total: 10, with_handoff: 4, won: 2, handoff_rate: 0.4, win_rate: 0.2 } as DashboardConversion;
    const { container } = render(<ConversionFunnel data={data} />);
    const comAjuda = Array.from(container.querySelectorAll("[title]")).filter((el) =>
      (el.getAttribute("title") ?? "").includes(AJUDA_GANHO),
    );
    expect(comAjuda.length).toBeGreaterThan(0);
    expect(comAjuda[0].textContent).toContain("Ganho");
  });
});
