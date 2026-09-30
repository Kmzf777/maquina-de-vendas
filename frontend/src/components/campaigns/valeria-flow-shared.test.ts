/**
 * `mensagemDeErro` — a leitura da FORMA DO ERRO do modal "ValerIA de Botões".
 *
 * Estes casos vieram de `valeria-flow-modal.test.tsx` junto com a função (ela desceu
 * para um módulo compartilhado para desfazer o ciclo casca ↔ painel de canais). Sem
 * docblock de ambiente de propósito: é função pura, e o default do repo é `node`.
 *
 * O que eles travam: o `detail` do FastAPI e o `error` do proxy do Next são AS DUAS
 * chaves em que a recusa pode chegar, e `detail` pode ser string, lista (422 do
 * Pydantic) ou objeto (`{problemas: [...]}`). Quem lesse só uma delas mostraria "Bad
 * Request" no lugar do motivo — o bug que `cadence-card.test.tsx` documenta ter
 * fechado, e que reapareceria aqui em silêncio.
 */
import { describe, expect, it } from "vitest";
import { mensagemDeErro } from "./valeria-flow-shared";

describe("mensagemDeErro", () => {
  it("prefere `detail` (FastAPI) e aceita `error` (o proxy do Next)", () => {
    expect(mensagemDeErro({ detail: "do backend" }, "padrão")).toBe("do backend");
    expect(mensagemDeErro({ error: "Backend indisponível" }, "padrão")).toBe("Backend indisponível");
  });

  it("junta as mensagens de um `detail` em lista (422 do Pydantic, problemas[])", () => {
    expect(mensagemDeErro({ detail: [{ msg: "campo obrigatório" }, { msg: "tipo inválido" }] }, "padrão"))
      .toBe("campo obrigatório · tipo inválido");
    expect(mensagemDeErro({ detail: { problemas: [{ mensagem: "nó N3 sem template" }] } }, "padrão"))
      .toBe("nó N3 sem template");
  });

  it("usa o padrão só quando não há mensagem nenhuma", () => {
    expect(mensagemDeErro({}, "padrão")).toBe("padrão");
    expect(mensagemDeErro(null, "padrão")).toBe("padrão");
    expect(mensagemDeErro({ detail: "   " }, "padrão")).toBe("padrão");
  });

  it("repassa o 503 que nomeia a migration, palavra por palavra", () => {
    const migration =
      "a migration 20260929_valeria_botoes.sql ainda não foi aplicada neste banco — " +
      "aplique-a no Supabase antes de editar ou ativar";
    expect(mensagemDeErro({ detail: migration }, "padrão")).toBe(migration);
  });
});
