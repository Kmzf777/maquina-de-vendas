/**
 * @vitest-environment jsdom
 *
 * Aviso do deep-link para lead sem conversa (cartão 70d844a6): com telefone
 * utilizável ganha o botão "Iniciar conversa"; sem telefone diz isso e não
 * oferece o botão. O link da ficha fica sempre.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { LeadSemConversaAviso } from "./lead-sem-conversa-aviso";

const responde = (status: number, body: unknown) =>
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: status === 200, status, json: async () => body })));

const lead = { id: "L1", name: "Micheli", phone: "5534988861441", company: null };

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("LeadSemConversaAviso", () => {
  it("com telefone: botão Iniciar conversa chama onIniciar", async () => {
    responde(200, { lead, telefone: "5534988861441", canais: [] });
    const onIniciar = vi.fn();
    render(<LeadSemConversaAviso leadId="L1" onIniciar={onIniciar} />);
    fireEvent.click(await screen.findByRole("button", { name: "Iniciar conversa" }));
    expect(onIniciar).toHaveBeenCalled();
    expect(screen.getByText("Este lead não tem conversa no WhatsApp.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Abrir ficha do lead" }).getAttribute("href")).toBe("/leads?lead_id=L1");
    expect(vi.mocked(fetch)).toHaveBeenCalledWith("/api/leads/L1/iniciar-conversa");
  });

  it("sem telefone: diz isso, sem botão, com link da ficha", async () => {
    responde(200, { lead: { ...lead, phone: "bling-1" }, telefone: null, canais: [] });
    render(<LeadSemConversaAviso leadId="L1" onIniciar={vi.fn()} />);
    expect(await screen.findByText("Este lead não tem telefone para WhatsApp.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Iniciar conversa" })).toBeNull();
    expect(screen.getByRole("link", { name: "Abrir ficha do lead" })).toBeTruthy();
  });

  it("carregando ou GET com erro: texto de hoje, sem botão", async () => {
    responde(500, { error: "falhou" });
    render(<LeadSemConversaAviso leadId="L1" onIniciar={vi.fn()} />);
    expect(screen.getByText("Este lead não tem conversa no WhatsApp.")).toBeTruthy();
    expect(screen.getByTestId("lead-sem-conversa")).toBeTruthy();
    await vi.waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByRole("button", { name: "Iniciar conversa" })).toBeNull();
    expect(screen.getByText("Este lead não tem conversa no WhatsApp.")).toBeTruthy();
  });
});
