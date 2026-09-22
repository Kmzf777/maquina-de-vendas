import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { displayCriterion, ValeriaScoreModal } from "./valeria-score-modal";

describe("ValeriaScoreModal", () => {
  it("renders an accessible title only while open", () => {
    expect(renderToStaticMarkup(createElement(ValeriaScoreModal, { open: true, onClose() {} }))).toContain("Valeria Score");
    expect(renderToStaticMarkup(createElement(ValeriaScoreModal, { open: false, onClose() {} }))).toBe("");
  });

  it("shows an unknown objective criterion as not identified", () => {
    expect(displayCriterion("segment", null)).toBe("Não identificado");
  });

  it("translates normalized score criteria for the seller", () => {
    expect(displayCriterion("supplier_reason", "replace")).toBe("Substituir fornecedor");
    expect(displayCriterion("purchase_timing", "within_15_days")).toBe("Em até 15 dias");
    expect(displayCriterion("segment", "wine_shop")).toBe("Adega");
  });
});
