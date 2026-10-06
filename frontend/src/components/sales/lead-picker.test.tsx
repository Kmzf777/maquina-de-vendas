/**
 * @vitest-environment jsdom
 *
 * Popover do Radix trocado pelo dublê (abrir o real trava o jsdom — ver
 * `popover-duble.test-utils.ts`).
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";

vi.mock("@/components/ui/popover", async () => {
  const { dublePopover } = await import("./popover-duble.test-utils");
  return dublePopover();
});

import { LeadPicker, leadsDaBusca } from "./lead-picker";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

const conversa = (leadId: string, name: string, extra: Record<string, unknown> = {}) => ({
  id: `conv-${leadId}-${Math.random()}`,
  leads: { id: leadId, name, phone: "5531999990000", email: null, cnpj: null, razao_social: null, ...extra },
});

describe("leadsDaBusca", () => {
  it("um lead por id, mesmo com duas conversas", () => {
    const out = leadsDaBusca([conversa("a", "Vida"), conversa("a", "Vida"), conversa("b", "Iago"), { id: "x", leads: null }]);
    expect(out.map((l) => l.id)).toEqual(["a", "b"]);
  });
  it("resposta que não é lista vira vazio", () => {
    expect(leadsDaBusca({ error: "x" })).toEqual([]);
  });
});

describe("LeadPicker", () => {
  it("busca no servidor com debounce, só a partir de 2 caracteres, e devolve o lead", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => [conversa("lead-9", "Vida Natural", { cnpj: "12345678000190" })],
    }) as Response);
    global.fetch = fetchMock as unknown as typeof fetch;
    const onEscolher = vi.fn();
    render(<LeadPicker selecionado={null} onEscolher={onEscolher} />);

    fireEvent.click(screen.getByRole("button", { name: /Selecione o lead/ }));
    const campo = screen.getByPlaceholderText("Buscar por nome, telefone, e-mail ou CNPJ...");

    fireEvent.change(campo, { target: { value: "v" } });
    await act(async () => { vi.advanceTimersByTime(500); });
    expect(fetchMock).not.toHaveBeenCalled();

    fireEvent.change(campo, { target: { value: "vi" } });
    fireEvent.change(campo, { target: { value: "vida" } });
    await act(async () => { vi.advanceTimersByTime(299); });
    expect(fetchMock).not.toHaveBeenCalled();
    await act(async () => { vi.advanceTimersByTime(1); });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/conversations/search-contacts?q=vida");

    vi.useRealTimers();
    const opcao = await screen.findByText("Vida Natural");
    fireEvent.click(opcao.closest("button")!);
    expect(onEscolher).toHaveBeenCalledWith(expect.objectContaining({ id: "lead-9", cnpj: "12345678000190" }));
  });

  it("mostra o lead escolhido no gatilho", () => {
    render(
      <LeadPicker selecionado={{ id: "l", name: "Iago", phone: "553199" }} onEscolher={vi.fn()} />,
    );
    expect(screen.getByRole("button", { name: /Iago/ })).toBeTruthy();
  });

  it("erro do servidor aparece em vez de 'nenhum lead'", async () => {
    global.fetch = vi.fn(async () => ({ ok: false, status: 500, json: async () => ({}) }) as Response) as unknown as typeof fetch;
    render(<LeadPicker selecionado={null} onEscolher={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /Selecione o lead/ }));
    fireEvent.change(screen.getByPlaceholderText("Buscar por nome, telefone, e-mail ou CNPJ..."), { target: { value: "vida" } });
    expect(await screen.findByText("Não foi possível buscar. Tente de novo.")).toBeTruthy();
  });
});
