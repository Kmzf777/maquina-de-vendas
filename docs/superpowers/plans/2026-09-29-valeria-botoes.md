# ValerIA de Botões — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Atendimento inbound 100% por botões, sem nenhuma chamada de LLM, da primeira mensagem do lead até o botão de encaminhamento, nos 4 setores — com mensagens e rótulos editáveis num modal em `/campanhas`.

**Architecture:** A estrutura do fluxo é **dado puro declarado em código** (`valeria_registry.py`, no papel do `campaigns/node_registry.py`); o conteúdo editável vive no banco e é override opcional (linha ausente = default do registry). O motor é um **intérprete do registry** — acha o nó, casa o clique com um botão declarado, devolve o destino declarado — e é função pura, testável sem mock. Todo I/O fica no runner.

**Tech Stack:** Python 3 / FastAPI / Supabase (backend), pytest (`asyncio_mode = auto`), Next.js App Router + React (frontend).

**Spec:** `docs/superpowers/specs/2026-09-29-valeria-botoes-design.md` — **leia antes da primeira task.** A §5 da spec é a FONTE do conteúdo dos 15 nós (corpo e rótulos); este plano não a duplica.

---

## Fases

| Fase | O que entrega | Roda sozinha? |
|---|---|---|
| **A — Motor** (Tasks 1–10) | O fluxo funcionando com os defaults do registry, sem UI | **Sim.** Tabela de conteúdo vazia = defaults. |
| **B — Modal** (Tasks 11–15) | O editor em `/campanhas` | Depende só do registry da Fase A. |

## Regras de execução com subagentes

Registradas porque já custaram trabalho perdido neste repo (`project_funil_joao_motor_followup`, "Armadilha de execução com subagentes num worktree compartilhado"):

- **Subagente NUNCA toca em git.** Proibido por nome: `add`, `commit`, `checkout`, `restore`, `reset`, `stash`, `rm`. O index é recurso compartilhado — o commit de um implementador leva os arquivos staged do outro. Quem commita é o orquestrador, entre ondas.
- Para ver versão antiga de um arquivo, o caminho seguro é `git show <sha>:<caminho>` — imprime sem tocar na árvore.
- `git status --short` entre ondas, sempre.
- **Se o plano estiver errado, o subagente PARA e reporta.** Não adivinha. Dois defeitos de plano foram pegos assim na última execução.

## Ondas de paralelismo

Arquivos não se cruzam dentro de uma onda.

| Onda | Tasks | Arquivos tocados |
|---|---|---|
| 1 | 1, 2, 3, 4 | `valeria_registry.py` · `meta.py` · `meta_parser.py` · migration |
| 2 | 5, 6, 7 | `valeria_engine.py` · `valeria_content.py` · `config.py`+`runner.py` |
| 3 | 8, 9 | `valeria_runner.py` · `campaigns/router.py` |
| 4 | 10 | `buffer/processor.py` — **sozinha, risco alto** |
| 5 | 11, 12 | rotas proxy do frontend · `valeria-flow-modal.tsx` (shell) |
| 6 | 13, 14 | `valeria-flow-editor.tsx` · `valeria-flow-channels.tsx` |
| 7 | 15 | `campanhas/page.tsx` |

---

# FASE A — O MOTOR

## Task 1: O registry (o contrato)

**Files:**
- Create: `backend/app/button_flow/valeria_registry.py`
- Test: `backend/tests/test_valeria_registry_2026_09_29.py`

Este é o arquivo que segura o desenho inteiro. Dado puro: **sem I/O, sem importar o motor** (import de volta fecharia ciclo — mesma regra do `campaigns/node_registry.py` e do `button_flow/flows.py`).

- [ ] **Step 1: Escreva o teste que falha**

```python
"""O registry da ValerIA de botões é o contrato entre a tela e o motor.

Espelha tests/test_node_registry.py: o teste cruza a declaração com as regras
que a Meta e o score impõem, para que um nó novo não entre sem destino nem um
rótulo longo demais chegue à produção (rótulo > 20 chars = a Meta recusa o
envio e a ValerIA fica MUDA naquele nó).
"""
from app.button_flow import valeria_registry as reg
from app.lead_score.model import CRITERIA_FIELDS


def test_flow_id_declarado():
    assert reg.FLOW_ID == "valeria_botoes_v1"


def test_todo_destino_existe():
    """Botão apontando para nó inexistente = lead parado para sempre."""
    conhecidos = set(reg.NOS) | set(reg.TERMINAIS)
    for no in reg.NOS.values():
        for botao in no.botoes:
            assert botao.destino in conhecidos, (
                f"{no.id}/{botao.id} aponta para {botao.destino!r}, que não existe"
            )


def test_todo_no_alcancavel_da_entrada():
    """Nó órfão é trabalho morto que a tela ainda oferece para editar."""
    vistos, fila = {reg.NO_ENTRADA}, [reg.NO_ENTRADA]
    while fila:
        atual = fila.pop()
        for botao in reg.NOS[atual].botoes:
            if botao.destino in reg.NOS and botao.destino not in vistos:
                vistos.add(botao.destino)
                fila.append(botao.destino)
    assert vistos == set(reg.NOS), f"órfãos: {sorted(set(reg.NOS) - vistos)}"


def test_limite_de_botoes_da_meta():
    """meta.py:326 levanta acima de 3; lista aceita até 10."""
    for no in reg.NOS.values():
        teto = reg.MAX_LINHAS_LISTA if no.tela == "lista" else reg.MAX_BOTOES
        assert 1 <= len(no.botoes) <= teto, f"{no.id} tem {len(no.botoes)} botões"


def test_rotulos_default_cabem_no_limite():
    for no in reg.NOS.values():
        limite = reg.LIMITE_TITULO_LISTA if no.tela == "lista" else reg.LIMITE_ROTULO_BOTAO
        for botao in no.botoes:
            assert len(botao.rotulo) <= limite, (
                f"{no.id}/{botao.id}: {len(botao.rotulo)} chars, limite {limite}"
            )


def test_ids_de_botao_unicos_dentro_do_no():
    """O motor casa o clique por id dentro do nó; id repetido é rota ambígua."""
    for no in reg.NOS.values():
        ids = [b.id for b in no.botoes]
        assert len(ids) == len(set(ids)), f"{no.id} tem id repetido: {ids}"


def test_grava_usa_campo_valido_do_score():
    for no in reg.NOS.values():
        for botao in no.botoes:
            for campo, _valor in botao.grava:
                assert campo in CRITERIA_FIELDS, f"{no.id}/{botao.id}: {campo!r}"


def test_corpo_nunca_vazio():
    for no in reg.NOS.values():
        assert no.corpo.strip(), f"{no.id} tem corpo vazio"


def test_foto_declarada_quando_a_tela_e_de_foto():
    for no in reg.NOS.values():
        if no.tela == "foto_botoes":
            assert no.foto, f"{no.id} é foto_botoes e não declara foto"


def test_n5b_nao_tem_o_botao_de_ver_outras():
    """'Uma vez só' é garantido pela TOPOLOGIA, não por contador no estado."""
    assert "ver_outras" not in {b.id for b in reg.NOS["N5b"].botoes}
    assert "ver_outras" not in {b.id for b in reg.NOS["P4b"].botoes}
```

- [ ] **Step 2: Rode e confirme que falha**

Run: `cd backend && python -m pytest tests/test_valeria_registry_2026_09_29.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.button_flow.valeria_registry'`

- [ ] **Step 3: Escreva o registry**

Comece pelas dataclasses e constantes:

```python
"""Estrutura do fluxo de botões da ValerIA. Dado puro, zero lógica.

O CONTRATO entre a tela (o modal de /campanhas) e o motor. Mesmo papel do
campaigns/node_registry.py, e pelo mesmo motivo: o cabeçalho daquele arquivo
documenta que o builder de cadências "foi construído e NUNCA foi usado — 16
campanhas, 0 ativas, 0 matrículas na história", e que toda falha medida tinha a
mesma raiz, a tela gravando uma chave e o motor lendo outra coisa no mesmo nome.

Aqui a tela só pode editar `corpo` e `rotulos`. Quem existe, quantos botões cada
nó tem e para onde cada botão vai é DECLARADO — não é editável, não vem do banco,
e é verificado por tests/test_valeria_registry_2026_09_29.py.

Leaf module: não importa nada de `app`, evitando ciclos de import.
"""
from __future__ import annotations

from dataclasses import dataclass, field

FLOW_ID = "valeria_botoes_v1"

# ── Limites da Meta (não são preferências: acima deles o envio é RECUSADO) ───
LIMITE_ROTULO_BOTAO = 20
LIMITE_TITULO_LISTA = 24
LIMITE_DESC_LISTA = 72
MAX_BOTOES = 3
MAX_LINHAS_LISTA = 10


@dataclass(frozen=True)
class Botao:
    """Um botão. `id` é o contrato estável; o rótulo é editável na tela.

    A Meta devolve o `id` no webhook (meta_parser.py:161 grava em `payload`), então
    editar "Cafeteria" para "Sou cafeteria" NÃO quebra a conversa de quem já
    recebeu a tela antiga. `rotulos_antigos` do banco cobre o resto.
    """
    id: str
    rotulo: str
    destino: str
    # ((campo_do_score, valor),) — gravado por save_score_evidence no clique.
    grava: tuple[tuple[str, object], ...] = ()
    # Só para linhas de lista: a segunda linha, que o botão comum não tem.
    descricao: str = ""


@dataclass(frozen=True)
class No:
    id: str
    rotulo_interno: str          # "N1 · Segmento" — só tela e log
    tela: str                    # "botoes" | "lista" | "foto_botoes"
    corpo: str
    botoes: tuple[Botao, ...]
    ramo: str
    foto: str | None = None      # caminho sob backend/app/photos/
    produto: str | None = None   # SKU declarado; o preço vem do catálogo no envio
    editaveis: tuple[str, ...] = ("corpo", "rotulos")


@dataclass(frozen=True)
class Terminal:
    id: str
    rotulo_interno: str
    vendedor: str | None = None
    corpo: str = ""
    tags: tuple[str, ...] = ()
    silenciar_ia: bool = False
    handoff: bool = False
    optout: bool = False
    # Quando preenchido, o terminal PERGUNTA o prazo em vez de encerrar.
    prazos: bool = False
```

Depois declare `NO_ENTRADA = "N0"`, o dict `NOS` com os 15 nós e o dict `TERMINAIS` com os 5.

**O conteúdo (corpo e rótulos de cada nó) está na §5 da spec** —
`docs/superpowers/specs/2026-09-29-valeria-botoes-design.md`. Ela é a fonte: copie
corpo, rótulos, destinos e a coluna "Grava" de lá, nó por nó. Não invente texto.

Os dois nós abaixo são o gabarito da forma — um de lista e um de botões com score:

```python
NOS: dict[str, No] = {
    "N0": No(
        id="N0", rotulo_interno="N0 · Setor", tela="lista", ramo="entrada",
        corpo=(
            "oi! aqui é a Valéria, do comercial da Café Canastra ☕\n\n"
            "pra eu já te levar pro que importa e não te encher de coisa que não "
            "tem a ver com você, me diz: o café é pra qual caso?"
        ),
        botoes=(
            Botao("negocio", "Pro meu negócio", "N1",
                  descricao="revenda, cafeteria, restaurante, hotel"),
            Botao("marca", "Com a minha marca", "P1",
                  descricao="café embalado com a sua logo"),
            Botao("consumo", "Pra consumo próprio", "C1",
                  descricao="em casa ou de presente"),
            Botao("exportacao", "Pra exportação", "E1",
                  descricao="mercado externo"),
        ),
    ),
    "N1": No(
        id="N1", rotulo_interno="N1 · Segmento", tela="botoes", ramo="atacado",
        corpo="boa! e que tipo de negócio você tem?",
        botoes=(
            # Os 15 segmentos do score têm só 3 FAIXAS de pontuação
            # (lead_score/model.py:16-31): cafeteria=2, as 9 lojas
            # especializadas=1, o resto=0. Por isso 3 botões bastam.
            Botao("cafeteria", "Cafeteria", "N2", grava=(("segment", "cafeteria"),)),
            Botao("loja", "Loja ou empório", "N2", grava=(("segment", "emporio"),)),
            Botao("outro", "Outro tipo", "N2", grava=(("segment", "other"),)),
        ),
    ),
    # ... os 13 restantes, conforme a §5 da spec
}
```

- [ ] **Step 4: Rode e confirme que passa**

Run: `cd backend && python -m pytest tests/test_valeria_registry_2026_09_29.py -v`
Expected: PASS, 10 testes.

- [ ] **Step 5: Reporte ao orquestrador.** NÃO commite. Liste os arquivos criados e a saída do pytest.

---

## Task 2: `send_interactive_list` e header de imagem

**Files:**
- Modify: `backend/app/whatsapp/meta.py` (perto de `send_interactive_buttons`, linha ~317)
- Modify: `backend/app/whatsapp/base.py` (a interface `WhatsAppProvider`)
- Modify: `backend/app/whatsapp/mock_provider.py`
- Test: `backend/tests/test_valeria_meta_interactive_2026_09_29.py`

`N0` tem 4 opções e `E1` tem 6 — hoje só existe o caminho de 1 a 3 botões, e `meta.py:326`
levanta `ValueError` acima disso. E o header de imagem é o que funde foto + preço + botões
numa mensagem faturada só.

- [ ] **Step 1: Escreva o teste que falha**

```python
"""send_interactive_list e o header de imagem do send_interactive_buttons.

O payload é conferido campo a campo porque a Meta recusa em silêncio (HTTP 200 com
`messages` ausente) quando a forma está errada — e recusa silenciosa aqui significa
lead sem resposta.
"""
import pytest

from app.whatsapp.meta import MetaCloudClient


class _Espiao(MetaCloudClient):
    """Captura o payload em vez de chamar a Meta."""
    def __init__(self):
        self.enviado = None

    async def _post(self, payload, request_type=""):
        self.enviado = payload
        return {"messages": [{"id": "wamid.TESTE"}]}


@pytest.mark.asyncio
async def test_lista_monta_sections_com_rows():
    cliente = _Espiao()
    await cliente.send_interactive_list(
        to="5534988861441", body="o café é pra qual caso?", button="Ver as opções",
        rows=[("negocio", "Pro meu negócio", "revenda, cafeteria"),
              ("marca", "Com a minha marca", "")],
    )
    interativo = cliente.enviado["interactive"]
    assert interativo["type"] == "list"
    assert interativo["body"]["text"] == "o café é pra qual caso?"
    assert interativo["action"]["button"] == "Ver as opções"
    linhas = interativo["action"]["sections"][0]["rows"]
    assert linhas[0] == {"id": "negocio", "title": "Pro meu negócio",
                         "description": "revenda, cafeteria"}
    # Descrição vazia sai FORA do payload: a Meta rejeita description="".
    assert linhas[1] == {"id": "marca", "title": "Com a minha marca"}


@pytest.mark.asyncio
async def test_lista_recusa_acima_de_10_linhas():
    cliente = _Espiao()
    with pytest.raises(ValueError, match="1 a 10"):
        await cliente.send_interactive_list(
            to="5534988861441", body="x", button="ver",
            rows=[(f"id{i}", f"t{i}", "") for i in range(11)],
        )


@pytest.mark.asyncio
async def test_botoes_com_image_url_viram_header():
    cliente = _Espiao()
    await cliente.send_interactive_buttons(
        to="5534988861441", body="gira em torno de R$28,70",
        buttons=[("sim", "Sim, quero falar")],
        image_url="https://exemplo/classico.jpg",
    )
    interativo = cliente.enviado["interactive"]
    assert interativo["header"] == {
        "type": "image", "image": {"link": "https://exemplo/classico.jpg"}
    }


@pytest.mark.asyncio
async def test_botoes_sem_image_url_nao_tem_header():
    """Regressão da recuperação: o fluxo existente não manda header."""
    cliente = _Espiao()
    await cliente.send_interactive_buttons(
        to="5534988861441", body="x", buttons=[("a", "A")],
    )
    assert "header" not in cliente.enviado["interactive"]
```

- [ ] **Step 2: Rode e confirme que falha**

Run: `cd backend && python -m pytest tests/test_valeria_meta_interactive_2026_09_29.py -v`
Expected: FAIL — `AttributeError: 'MetaCloudClient' object has no attribute 'send_interactive_list'`

- [ ] **Step 3: Implemente**

Em `meta.py`, adicione o parâmetro `image_url` ao `send_interactive_buttons` (mantendo a
assinatura atual compatível) e monte o header só quando ele vier:

```python
    async def send_interactive_buttons(
        self, to: str, body: str, buttons: list[tuple[str, str]],
        image_url: str | None = None,
    ) -> dict:
        if not 1 <= len(buttons) <= 3:
            raise ValueError(
                f"send_interactive_buttons aceita de 1 a 3 botões, recebeu {len(buttons)}"
            )
        interactive: dict = {
            "type": "button",
            "body": {"text": body},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": bid, "title": titulo}}
                    for bid, titulo in buttons
                ]
            },
        }
        # Header de imagem é o que funde foto + preço + botões numa mensagem só.
        # Desde 01/10/2026 a Meta cobra por mensagem enviada inclusive dentro da
        # janela de 24h, então cada bolha economizada é dinheiro.
        if image_url:
            interactive["header"] = {"type": "image", "image": {"link": image_url}}
        ...
```

E o método novo:

```python
    async def send_interactive_list(
        self, to: str, body: str, button: str,
        rows: list[tuple[str, str, str]], header: str | None = None,
    ) -> dict:
        """Mensagem de lista: até 10 linhas, cada uma com id, título e descrição.

        Existe porque N0 tem 4 opções e E1 tem 6, e o caminho de botões recusa
        acima de 3. A linha de lista também aceita DESCRIÇÃO, que o botão não
        tem — é o que deixa a entrada explicar cada setor em uma linha.

        `rows` é (id, titulo, descricao); descrição vazia sai fora do payload,
        porque a Meta rejeita `description: ""`.
        """
        if not 1 <= len(rows) <= 10:
            raise ValueError(
                f"send_interactive_list aceita de 1 a 10 linhas, recebeu {len(rows)}"
            )
        linhas = []
        for rid, titulo, descricao in rows:
            linha = {"id": rid, "title": titulo}
            if descricao:
                linha["description"] = descricao
            linhas.append(linha)
        interactive: dict = {
            "type": "list",
            "body": {"text": body},
            "action": {"button": button, "sections": [{"rows": linhas}]},
        }
        if header:
            interactive["header"] = {"type": "text", "text": header}
        result = await self._post({
            "messaging_product": "whatsapp",
            **_recipient_field(to),
            "type": "interactive",
            "interactive": interactive,
        }, request_type="send_interactive_list")
        messages = result.get("messages")
        if not isinstance(messages, list) or not messages:
            raise RuntimeError(
                f"Meta send_interactive_list rejected (missing messages): {result!r}"
            )
        return result
```

Declare `send_interactive_list` na interface de `base.py` e implemente no `mock_provider.py`
no mesmo estilo dos métodos vizinhos.

- [ ] **Step 4: Rode e confirme que passa**

Run: `cd backend && python -m pytest tests/test_valeria_meta_interactive_2026_09_29.py tests/test_button_flow_provider_2026_08_20.py -v`
Expected: PASS nos 4 novos **e** nos do provider antigo (regressão da recuperação).

- [ ] **Step 5: Reporte ao orquestrador.** NÃO commite.

---

## Task 3: `list_reply` deixa de ser texto

**Files:**
- Modify: `backend/app/webhook/meta_parser.py:164-167`
- Test: `backend/tests/test_valeria_parser_list_reply_2026_09_29.py`

Hoje o parser rebaixa `list_reply` para `parsed_type = "text"`, com o comentário *"Listas
estão fora do escopo do bot de botões — segue como texto"*. Com `N0` e `E1` sendo listas,
**o clique chegaria ao motor como texto livre e dispararia nudge em vez de avançar** — o
fluxo morreria na primeira tela.

- [ ] **Step 1: Escreva o teste que falha**

```python
"""Clique em linha de lista é CLIQUE, não texto.

meta_parser.py rebaixava list_reply para texto. Com N0 (entrada, 4 opções) e E1
(destino, 6 mercados) sendo listas, o fluxo da ValerIA morreria na primeira tela:
o toque viraria texto livre e o motor responderia com nudge.
"""
from app.webhook.meta_parser import parse_meta_webhook


def _envelope(interactive: dict) -> dict:
    return {"entry": [{"changes": [{"value": {
        "messaging_product": "whatsapp",
        "metadata": {"phone_number_id": "111", "display_phone_number": "5534999"},
        "messages": [{
            "from": "5534988861441", "id": "wamid.X", "timestamp": "1700000000",
            "type": "interactive", "interactive": interactive,
        }],
    }}]}]}


def test_list_reply_vira_clique_com_id_no_payload():
    msgs = parse_meta_webhook(_envelope({
        "type": "list_reply",
        "list_reply": {"id": "negocio", "title": "Pro meu negócio",
                       "description": "revenda"},
    }))
    assert len(msgs) == 1
    assert msgs[0].message_type == "button"
    assert msgs[0].metadata["payload"] == "negocio"
    assert msgs[0].metadata["title"] == "Pro meu negócio"


def test_list_reply_sem_id_cai_no_titulo():
    msgs = parse_meta_webhook(_envelope({
        "type": "list_reply", "list_reply": {"title": "Europa"},
    }))
    assert msgs[0].metadata["payload"] == "Europa"


def test_button_reply_segue_igual():
    """Regressão: a recuperação depende deste caminho."""
    msgs = parse_meta_webhook(_envelope({
        "type": "button_reply",
        "button_reply": {"id": "repor", "title": "Preciso repor"},
    }))
    assert msgs[0].message_type == "button"
    assert msgs[0].metadata["payload"] == "repor"
```

**Se `parse_meta_webhook` não for o nome real da função, ou os objetos devolvidos não
tiverem `.message_type`/`.metadata`, PARE e reporte.** Confira em
`backend/tests/test_button_flow_parser_2026_08_20.py`, que já exercita esse parser, e use
a forma que ele usa.

- [ ] **Step 2: Rode e confirme que falha**

Run: `cd backend && python -m pytest tests/test_valeria_parser_list_reply_2026_09_29.py -v`
Expected: FAIL em `test_list_reply_vira_clique_com_id_no_payload` — `message_type` vem `"text"`.

- [ ] **Step 3: Implemente**

Substitua o bloco de `list_reply` (`meta_parser.py:164-167`):

```python
                    elif interactive_type == "list_reply":
                        # Mensagem de lista NOSSA: o `id` é controlado por nós, igual
                        # ao button_reply. Isto era `parsed_type = "text"` até
                        # 29/09/2026, e com N0/E1 sendo listas o clique viraria texto
                        # livre — o motor responderia nudge e o fluxo morreria na
                        # primeira tela.
                        reply = interactive.get("list_reply", {})
                        text = reply.get("title", "")
                        parsed_type = "button"
                        metadata_dict = {
                            "payload": reply.get("id") or text,
                            "title": text,
                        }
```

- [ ] **Step 4: Rode e confirme que passa**

Run: `cd backend && python -m pytest tests/test_valeria_parser_list_reply_2026_09_29.py tests/test_button_flow_parser_2026_08_20.py -v`
Expected: PASS nos 3 novos e em toda a suíte do parser antigo.

- [ ] **Step 5: Reporte ao orquestrador.** NÃO commite.

---

## Task 4: Migration

**Files:**
- Create: `supabase/migrations/20260929_valeria_botoes.sql`
- Test: `backend/tests/test_valeria_migration_2026_09_29.py`

Siga o formato de `supabase/migrations/20260820_button_flow_agent.sql` e o estilo de teste
de `backend/tests/test_button_flow_migration_2026_08_20.py` (**leia os dois antes**: o teste
de migration deste repo confere o TEXTO do SQL, não roda o banco).

- [ ] **Step 1: Escreva o teste que falha**

```python
"""A migration da ValerIA de botões, conferida pelo texto do SQL.

Mesmo espírito de test_button_flow_migration_2026_08_20.py: não sobe banco, garante
que o arquivo declara o que o código espera encontrar. O código roda SEM a migration
(carregar() é fail-open e devolve os defaults do registry), então o que este teste
protege é a tela e o "Ativar", não o fluxo.
"""
from pathlib import Path

SQL = (Path(__file__).resolve().parents[2] / "supabase" / "migrations"
       / "20260929_valeria_botoes.sql").read_text(encoding="utf-8")


def test_cria_a_tabela_de_conteudo():
    assert "create table" in SQL.lower()
    assert "valeria_flow_content" in SQL


def test_colunas_que_o_codigo_le():
    for coluna in ("flow_id", "node_id", "corpo", "rotulos", "rotulos_antigos"):
        assert coluna in SQL, f"coluna {coluna} não declarada"


def test_unicidade_por_no():
    """Sem isso, dois overrides do mesmo nó e o carregador escolhe um ao acaso."""
    assert "unique" in SQL.lower()
    assert "flow_id" in SQL and "node_id" in SQL


def test_agent_profiles_ganha_flow_id():
    assert "alter table" in SQL.lower()
    assert "agent_profiles" in SQL
    assert "flow_id" in SQL


def test_tags_semeadas_com_nome_exato():
    """add_tags_to_lead resolve por NOME e devolve em silêncio se não achar —
    nome divergente aqui não levanta nada, só perde a tag."""
    for tag in ("Botões: Qualificado", "Botões: Adiado",
                "Botões: Atendimento humano", "Botões: Opt-out"):
        assert tag in SQL, f"tag {tag!r} não semeada"


def test_rls_declarada():
    assert "enable row level security" in SQL.lower()
    assert "create policy" in SQL.lower()
```

- [ ] **Step 2: Rode e confirme que falha**

Run: `cd backend && python -m pytest tests/test_valeria_migration_2026_09_29.py -v`
Expected: FAIL — `FileNotFoundError`.

- [ ] **Step 3: Escreva a migration**

```sql
-- ValerIA de botões: conteúdo editável do fluxo + o fluxo que cada perfil roda.
--
-- §1 é OVERRIDE, não fonte: linha ausente = default de
-- app/button_flow/valeria_registry.py. O fluxo roda com esta tabela VAZIA, de
-- propósito — migration pendente é um modo de falha recorrente neste repo, e
-- aqui ele não pode emudecer a ValerIA.

-- ─── §1 Conteúdo editável ──────────────────────────────────────────────────
create table if not exists valeria_flow_content (
  id              uuid primary key default gen_random_uuid(),
  flow_id         text not null,
  node_id         text not null,
  corpo           text,
  rotulos         jsonb,
  -- Histórico: quem recebeu a tela antiga e clica depois manda o id antigo. O id
  -- não muda, então isto é rede para o caso de payload que só traz o título.
  rotulos_antigos jsonb not null default '[]'::jsonb,
  updated_at      timestamptz not null default now(),
  updated_by      uuid references auth.users(id),
  unique (flow_id, node_id)
);

alter table valeria_flow_content enable row level security;

create policy "valeria_flow_content_leitura" on valeria_flow_content
  for select to authenticated using (true);

create policy "valeria_flow_content_escrita" on valeria_flow_content
  for all to authenticated
  using (exists (select 1 from users u where u.id = auth.uid() and u.role = 'admin'))
  with check (exists (select 1 from users u where u.id = auth.uid() and u.role = 'admin'));

-- ─── §2 Qual fluxo o perfil roda ───────────────────────────────────────────
-- kind='button_flow' hoje só sabe de UM fluxo (runner.py assume recuperacao_v1).
-- Com dois, o perfil precisa dizer qual. NULL = 'recuperacao_v1', para o perfil
-- que já existe em produção continuar funcionando sem UPDATE.
--
-- Coluna nova e NÃO prompt_key reaproveitado: nome com dois significados é
-- exatamente a classe de bug que campaigns/node_registry.py documenta.
alter table agent_profiles add column if not exists flow_id text;

comment on column agent_profiles.flow_id is
  'Fluxo de botões que este perfil roda. NULL = recuperacao_v1. Ignorado quando kind=llm.';

-- ─── §3 Tags de desfecho ───────────────────────────────────────────────────
-- Por NOME EXATO: add_tags_to_lead resolve por nome e devolve em silêncio se não
-- achar, então nome divergente aqui não levanta erro nenhum — só perde a tag.
insert into tags (name, color)
values ('Botões: Qualificado',        '#16A34A'),
       ('Botões: Adiado',             '#CA8A04'),
       ('Botões: Atendimento humano', '#2563EB'),
       ('Botões: Opt-out',            '#DC2626')
on conflict (name) do nothing;
```

**Se a tabela `tags` não tiver as colunas `name`/`color`, ou `users.role` não for o lugar
do papel de admin, PARE e reporte.** Confira contra `20260820_button_flow_agent.sql`, que
já semeia tags, e contra uma migration que já declare RLS por admin.

- [ ] **Step 4: Rode e confirme que passa**

Run: `cd backend && python -m pytest tests/test_valeria_migration_2026_09_29.py -v`
Expected: PASS, 6 testes.

- [ ] **Step 5: Reporte ao orquestrador.** NÃO commite.

---

## Task 5: O motor (função pura)

**Files:**
- Create: `backend/app/button_flow/valeria_engine.py`
- Test: `backend/tests/test_valeria_engine_2026_09_29.py`

Depende da Task 1. Reusa `Clique`, `Texto`, `Decisao`, `Mensagem`, `Efeitos`, `normalizar`
de `button_flow/engine.py` — **não estende `decidir()`**, que tem a matriz da recuperação
embutida (`NO_INTERESSE`, `NO_PRAZO`, trilhas).

- [ ] **Step 1: Escreva o teste que falha**

```python
"""Matriz nó × evento do fluxo da ValerIA, sem um único mock.

O motor é um INTÉRPRETE do registry: acha o nó, casa o clique com um botão
declarado, devolve o destino declarado. Como a estrutura é dado, esta matriz
cobre o comportamento inteiro sem tocar em banco, rede ou relógio.
"""
import pytest

from app.button_flow import valeria_registry as reg
from app.button_flow import valeria_engine as motor
from app.button_flow.engine import Clique, Texto

VAZIO: dict = {}


def _clique(botao_id: str) -> Clique:
    return Clique(payload=botao_id, titulo="")


# ── Caminho felizes ────────────────────────────────────────────────────────
def test_clique_vai_para_o_destino_declarado():
    d = motor.decidir("N0", _clique("negocio"), VAZIO, reg.NOS, reg.TERMINAIS)
    assert d.proximo_no == "N1"
    assert d.mensagem is not None
    assert d.mensagem.corpo == reg.NOS["N1"].corpo


def test_clique_grava_o_campo_do_score():
    d = motor.decidir("N1", _clique("cafeteria"), VAZIO, reg.NOS, reg.TERMINAIS)
    assert d.criterios == {"segment": "cafeteria"}


def test_clique_em_terminal_de_handoff():
    d = motor.decidir("N5", _clique("sim"), VAZIO, reg.NOS, reg.TERMINAIS)
    assert d.proximo_no == "T_HANDOFF"
    assert d.efeitos.handoff is True
    assert "Botões: Qualificado" in d.efeitos.tags


def test_clique_de_rotulo_antigo_ainda_resolve():
    """Editar o rótulo não pode matar quem recebeu a tela antiga."""
    estado = {"rotulos_antigos": {"N1": {"Cafeteria": "cafeteria"}}}
    d = motor.decidir("N1", Clique(payload="Cafeteria", titulo="Cafeteria"),
                      estado, reg.NOS, reg.TERMINAIS)
    assert d.proximo_no == "N2"


# ── A trava de insistência ─────────────────────────────────────────────────
@pytest.mark.parametrize("nudges_antes,espera_bloqueio", [(0, False), (1, False),
                                                          (2, False), (3, True)])
def test_texto_livre_reenvia_ate_3_e_bloqueia_no_4o(nudges_antes, espera_bloqueio):
    estado = {"nudges": nudges_antes}
    d = motor.decidir("N1", Texto("quanto custa o kg?"), estado, reg.NOS, reg.TERMINAIS)
    if espera_bloqueio:
        assert d.proximo_no == "T_HUMANO"
        assert d.efeitos.silenciar_ia is True
        assert d.mensagem is None, "BLOCK não gasta mensagem"
    else:
        assert d.proximo_no == "N1", "nudge reenvia o MESMO nó"
        assert d.marcar_nudge is True
        assert d.mensagem is not None


def test_contador_de_nudge_e_por_atendimento_nao_por_no():
    """Por nó, 17 nós dariam 51 nudges em vez de 3."""
    estado = {"nudges": 3}
    for no in ("N1", "N2", "P1", "E2"):
        d = motor.decidir(no, Texto("oi"), estado, reg.NOS, reg.TERMINAIS)
        assert d.proximo_no == "T_HUMANO", f"{no} deu nudge com o teto já estourado"


def test_clique_valido_nao_gasta_nudge():
    estado = {"nudges": 2}
    d = motor.decidir("N1", _clique("cafeteria"), estado, reg.NOS, reg.TERMINAIS)
    assert d.marcar_nudge is False


# ── Opt-out sem IA ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("frase", ["pare", "PARAR", "parar", "sair",
                                   "me tira", "descadastrar", "não quero mais"])
def test_optout_por_lista_fechada_antes_do_contador(frase):
    d = motor.decidir("N2", Texto(frase), {"nudges": 0}, reg.NOS, reg.TERMINAIS)
    assert d.proximo_no == "T_OPTOUT"
    assert d.efeitos.optout is True
    assert d.marcar_nudge is False, "opt-out não gasta nudge"


@pytest.mark.parametrize("frase", ["não quero trocar de fornecedor",
                                   "quero parar de comprar do meu fornecedor atual",
                                   "onde vocês ficam?"])
def test_frase_que_contem_a_palavra_nao_e_optout(frase):
    """Casamento por IGUALDADE normalizada, nunca substring."""
    d = motor.decidir("N2", Texto(frase), {"nudges": 0}, reg.NOS, reg.TERMINAIS)
    assert d.proximo_no == "N2"
    assert d.efeitos.optout is False


# ── "Ver outras opções": a topologia garante uma vez só ────────────────────
def test_ver_outras_vai_para_n5b_e_n5b_nao_reoferece():
    d = motor.decidir("N5", _clique("ver_outras"), VAZIO, reg.NOS, reg.TERMINAIS)
    assert d.proximo_no == "N5b"
    assert "ver_outras" not in {b.id for b in reg.NOS["N5b"].botoes}


# ── Invariantes de segurança ───────────────────────────────────────────────
def test_clique_desconhecido_cai_no_nudge_nao_em_erro():
    d = motor.decidir("N1", _clique("id_que_nao_existe"), {"nudges": 0},
                      reg.NOS, reg.TERMINAIS)
    assert d.proximo_no == "N1"
    assert d.marcar_nudge is True


def test_no_desconhecido_entrega_ao_humano_em_vez_de_estourar():
    """flow_state corrompido não pode virar exceção no caminho do inbound."""
    d = motor.decidir("NO_QUE_NAO_EXISTE", _clique("x"), VAZIO, reg.NOS, reg.TERMINAIS)
    assert d.proximo_no == "T_HUMANO"
    assert d.mensagem is None


# ── T_ADIAR pergunta QUANDO, nunca SE ──────────────────────────────────────
def test_nao_agora_vai_para_t_adiar_e_PERGUNTA_o_prazo():
    """Medido: 'ainda tenho estoque' não é um não — 4 de 9 voltaram e um fechou
    R$ 5.500. O terminal de adiamento tem mensagem e botões, não é encerramento."""
    d = motor.decidir("N5", _clique("nao_agora"), VAZIO, reg.NOS, reg.TERMINAIS)
    assert d.proximo_no == "T_ADIAR"
    assert d.mensagem is not None, "T_ADIAR encerrou em vez de perguntar"
    assert len(d.mensagem.botoes) == 3, "os 30/60/90 de flows.PRAZOS"
    assert d.efeitos.optout is False, "adiar NÃO descarta o lead"


@pytest.mark.parametrize("prazo_id,dias", [("snooze30", 30), ("snooze60", 60),
                                            ("snooze90", 90)])
def test_clique_no_prazo_agenda_recontato(prazo_id, dias):
    d = motor.decidir("T_ADIAR", _clique(prazo_id), VAZIO, reg.NOS, reg.TERMINAIS)
    assert d.efeitos.recontato_dias == dias
    assert d.efeitos.optout is False


def test_consumo_sem_clique_encerra_sem_descartar():
    """consumo.py: 'Consumo não é encerramento definitivo'. opt_out fica FALSE."""
    terminal = reg.TERMINAIS["T_FIM"]
    assert terminal.optout is False
    assert terminal.corpo == "", "T_FIM não gasta mensagem"
```

- [ ] **Step 2: Rode e confirme que falha**

Run: `cd backend && python -m pytest tests/test_valeria_engine_2026_09_29.py -v`
Expected: FAIL — `ModuleNotFoundError: app.button_flow.valeria_engine`

- [ ] **Step 3: Implemente**

`Decisao` de `engine.py` **não tem** o campo `criterios` que o teste exige. Declare uma
subclasse local em `valeria_engine.py` em vez de mexer na `Decisao` da recuperação:

```python
"""Motor do fluxo de botões da ValerIA. Núcleo puro: sem banco, sem rede, sem relógio.

Intérprete do registry, não matriz de `if`: como valeria_registry.py declara os
destinos, decidir() só precisa achar o nó, casar o clique com um botão e devolver o
destino declarado. É por isso que este arquivo é curto.

Reusa os eventos e a saída de button_flow/engine.py de propósito — o runner já sabe
aplicar `Decisao`. Não estende `engine.decidir()`, que tem a matriz da recuperação
embutida (NO_INTERESSE, NO_PRAZO, trilhas) e ficaria ilegível servindo dois fluxos.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from app.button_flow.engine import (
    Clique, Decisao as DecisaoBase, Efeitos, Mensagem, Texto, normalizar,
)
from app.button_flow import valeria_registry as reg


@dataclass(frozen=True)
class Decisao(DecisaoBase):
    """`Decisao` da recuperação + os critérios de score que o clique revelou.

    Campo novo aqui e não na base: a recuperação não tem score, e acrescentar
    campo na dataclass dela obrigaria a revisar todos os call sites daquele fluxo.
    """
    criterios: dict = field(default_factory=dict)


TETO_NUDGES = 3

# Opt-out sem IA. Casamento por IGUALDADE normalizada, NUNCA substring: "não quero
# trocar de fornecedor" contém "não quero" e não é pedido de saída. A Meta exige
# honrar o pedido de parar, e sem modelo esta lista é o único jeito de detectá-lo.
FRASES_OPTOUT = frozenset({
    normalizar(f) for f in (
        "pare", "parar", "para", "sair", "me tira", "me tire", "remover",
        "descadastrar", "nao quero mais", "não quero mais", "cancelar",
        "para de mandar", "pare de mandar", "nao me manda mais",
    )
})
```

Depois `decidir(no_atual, evento, estado, nos, terminais) -> Decisao`, nesta ordem:

1. `no_atual` desconhecido → `T_HUMANO`, sem mensagem (flow_state corrompido não estoura).
2. `isinstance(evento, Texto)` e `normalizar(conteudo) in FRASES_OPTOUT` → `T_OPTOUT`.
3. `isinstance(evento, Clique)` → casa `payload` com `botao.id`; se não casar, tenta
   `estado["rotulos_antigos"][no_atual]`; casou → monta a `Decisao` do destino.
4. Resto (texto livre ou clique não reconhecido) → nudge se `estado.get("nudges", 0) <
   TETO_NUDGES`, senão `T_HUMANO` sem mensagem.

- [ ] **Step 4: Rode e confirme que passa**

Run: `cd backend && python -m pytest tests/test_valeria_engine_2026_09_29.py tests/test_button_flow_engine_2026_08_20.py -v`
Expected: PASS nos novos **e** em toda a suíte do motor da recuperação.

- [ ] **Step 5: Reporte ao orquestrador.** NÃO commite.

---

## Task 6: Conteúdo editável (fail-open)

**Files:**
- Create: `backend/app/button_flow/valeria_content.py`
- Test: `backend/tests/test_valeria_content_2026_09_29.py`

Depende da Task 1.

- [ ] **Step 1: Escreva o teste que falha**

```python
"""Overrides de conteúdo: o banco sobrescreve o registry, e a ausência dele não quebra.

O fluxo TEM que rodar com a tabela vazia ou inexistente. Migration pendente é um
modo de falha recorrente neste repo, e aqui ele emudeceria a ValerIA.
"""
from app.button_flow import valeria_content as conteudo
from app.button_flow import valeria_registry as reg


def test_sem_override_devolve_o_default_do_registry():
    nos = conteudo.aplicar(reg.NOS, {})
    assert nos["N1"].corpo == reg.NOS["N1"].corpo
    assert nos["N1"].botoes[0].rotulo == reg.NOS["N1"].botoes[0].rotulo


def test_override_de_corpo():
    nos = conteudo.aplicar(reg.NOS, {"N1": {"corpo": "qual seu segmento?"}})
    assert nos["N1"].corpo == "qual seu segmento?"
    assert nos["N2"].corpo == reg.NOS["N2"].corpo, "não vaza para outro nó"


def test_override_de_rotulo_por_id_e_parcial():
    nos = conteudo.aplicar(reg.NOS, {"N1": {"rotulos": {"cafeteria": "Sou cafeteria"}}})
    por_id = {b.id: b.rotulo for b in nos["N1"].botoes}
    assert por_id["cafeteria"] == "Sou cafeteria"
    assert por_id["loja"] == "Loja ou empório", "id ausente mantém o default"


def test_override_nunca_muda_o_destino():
    """A tela edita texto. Rota é estrutura, e estrutura é código."""
    nos = conteudo.aplicar(reg.NOS, {"N1": {"rotulos": {"cafeteria": "X"},
                                            "destino": "T_OPTOUT"}})
    assert nos["N1"].botoes[0].destino == reg.NOS["N1"].botoes[0].destino


def test_no_desconhecido_no_override_e_ignorado():
    nos = conteudo.aplicar(reg.NOS, {"NO_QUE_NAO_EXISTE": {"corpo": "x"}})
    assert set(nos) == set(reg.NOS)


def test_carregar_devolve_vazio_quando_o_banco_falha(monkeypatch):
    def explode():
        raise RuntimeError("relation valeria_flow_content does not exist")
    monkeypatch.setattr(conteudo, "get_supabase", lambda: explode())
    assert conteudo.carregar(reg.FLOW_ID) == {}


# ── Validação, que é o que impede a ValerIA de emudecer ───────────────────
def test_rotulo_acima_do_limite_e_rejeitado():
    erro = conteudo.validar("N1", {"rotulos": {"cafeteria": "U" * 21}})
    assert erro and "20" in erro


def test_corpo_vazio_e_rejeitado():
    assert conteudo.validar("N1", {"corpo": "   "})


def test_titulo_de_lista_usa_o_limite_de_24():
    assert conteudo.validar("N0", {"rotulos": {"negocio": "U" * 25}})
    assert conteudo.validar("N0", {"rotulos": {"negocio": "U" * 24}}) is None


def test_rotulo_no_limite_passa():
    assert conteudo.validar("N1", {"rotulos": {"cafeteria": "U" * 20}}) is None
```

- [ ] **Step 2: Rode e confirme que falha**

Run: `cd backend && python -m pytest tests/test_valeria_content_2026_09_29.py -v`
Expected: FAIL — `ModuleNotFoundError: app.button_flow.valeria_content`

- [ ] **Step 3: Implemente**

Três funções públicas: `carregar(flow_id) -> dict` (I/O, fail-open com log),
`aplicar(nos, overrides) -> dict` (pura, usa `dataclasses.replace`) e
`validar(node_id, payload) -> str | None` (pura, devolve a mensagem de erro ou `None`).

`aplicar` só olha as chaves `corpo` e `rotulos` — qualquer outra é ignorada, e é assim que
`test_override_nunca_muda_o_destino` passa: não há caminho para escrever `destino`.

- [ ] **Step 4: Rode e confirme que passa**

Run: `cd backend && python -m pytest tests/test_valeria_content_2026_09_29.py -v`
Expected: PASS, 10 testes.

- [ ] **Step 5: Reporte ao orquestrador.** NÃO commite.

---

## Task 7: O gate por fluxo

**Files:**
- Modify: `backend/app/button_flow/config.py`
- Modify: `backend/app/button_flow/runner.py:88-118`
- Test: `backend/tests/test_valeria_gate_2026_09_29.py`

**Risco alto: este é o gate da Recuperação.** `config.enabled()` hoje lê
`RECUPERACAO_ENABLED` e fecha o gate dos **dois** fluxos. Ligar a ValerIA por essa chave
armaria a Recuperação junto — que está desligada e tem 3 bloqueantes pendentes.

- [ ] **Step 1: Escreva o teste que falha**

```python
"""O gate passa a ser POR FLUXO, e os dois fluxos são independentes.

Uma env var fechava os dois: ligar a ValerIA de botões armaria a Recuperação junto.
"""
import pytest

from app.button_flow import config, runner

FLUXO_VALERIA = "valeria_botoes_v1"
FLUXO_RECUP = "recuperacao_v1"


def test_ambos_desligados_por_default(monkeypatch):
    monkeypatch.delenv("RECUPERACAO_ENABLED", raising=False)
    monkeypatch.delenv("VALERIA_BOTOES_ENABLED", raising=False)
    assert config.enabled(FLUXO_RECUP) is False
    assert config.enabled(FLUXO_VALERIA) is False


def test_ligar_a_valeria_nao_liga_a_recuperacao(monkeypatch):
    monkeypatch.delenv("RECUPERACAO_ENABLED", raising=False)
    monkeypatch.setenv("VALERIA_BOTOES_ENABLED", "on")
    assert config.enabled(FLUXO_VALERIA) is True
    assert config.enabled(FLUXO_RECUP) is False


def test_ligar_a_recuperacao_nao_liga_a_valeria(monkeypatch):
    monkeypatch.setenv("RECUPERACAO_ENABLED", "on")
    monkeypatch.delenv("VALERIA_BOTOES_ENABLED", raising=False)
    assert config.enabled(FLUXO_RECUP) is True
    assert config.enabled(FLUXO_VALERIA) is False


def test_fluxo_desconhecido_e_desligado(monkeypatch):
    monkeypatch.setenv("VALERIA_BOTOES_ENABLED", "on")
    monkeypatch.setenv("RECUPERACAO_ENABLED", "on")
    assert config.enabled("fluxo_que_nao_existe") is False


# ── O resolvedor de fluxo da conversa ─────────────────────────────────────
def test_perfil_sem_flow_id_e_recuperacao(monkeypatch):
    """Compatibilidade: o perfil que já existe em produção não tem a coluna."""
    monkeypatch.setenv("RECUPERACAO_ENABLED", "on")
    monkeypatch.setattr(runner, "get_agent_profile",
                        lambda _id: {"kind": "button_flow", "flow_id": None})
    runner.limpar_cache_de_perfis()
    assert runner.fluxo_da_conversa({"agent_profile_id": "p1"}, {}) == FLUXO_RECUP


def test_perfil_com_flow_id_da_valeria(monkeypatch):
    monkeypatch.setenv("VALERIA_BOTOES_ENABLED", "on")
    monkeypatch.setattr(runner, "get_agent_profile",
                        lambda _id: {"kind": "button_flow", "flow_id": FLUXO_VALERIA})
    runner.limpar_cache_de_perfis()
    assert runner.fluxo_da_conversa({"agent_profile_id": "p1"}, {}) == FLUXO_VALERIA


def test_perfil_llm_nao_tem_fluxo(monkeypatch):
    monkeypatch.setenv("VALERIA_BOTOES_ENABLED", "on")
    monkeypatch.setattr(runner, "get_agent_profile",
                        lambda _id: {"kind": "llm", "flow_id": None})
    runner.limpar_cache_de_perfis()
    assert runner.fluxo_da_conversa({"agent_profile_id": "p1"}, {}) is None


def test_fluxo_com_a_chave_desligada_e_none(monkeypatch):
    monkeypatch.delenv("VALERIA_BOTOES_ENABLED", raising=False)
    monkeypatch.setattr(runner, "get_agent_profile",
                        lambda _id: {"kind": "button_flow", "flow_id": FLUXO_VALERIA})
    runner.limpar_cache_de_perfis()
    assert runner.fluxo_da_conversa({"agent_profile_id": "p1"}, {}) is None


def test_conversa_vence_o_canal(monkeypatch):
    """runner.py:96 — os canais da ValerIA e do João apontam para o MESMO perfil."""
    monkeypatch.setenv("VALERIA_BOTOES_ENABLED", "on")
    monkeypatch.setattr(runner, "get_agent_profile",
                        lambda _id: {"kind": "button_flow", "flow_id": FLUXO_VALERIA})
    runner.limpar_cache_de_perfis()
    canal = {"agent_profiles": {"kind": "llm", "flow_id": None}}
    assert runner.fluxo_da_conversa({"agent_profile_id": "p1"}, canal) == FLUXO_VALERIA


def test_erro_ao_resolver_e_fail_open(monkeypatch):
    """Fail-CLOSED sequestraria conversa humana num erro de leitura."""
    monkeypatch.setenv("VALERIA_BOTOES_ENABLED", "on")
    def explode(_id):
        raise RuntimeError("banco fora")
    monkeypatch.setattr(runner, "get_agent_profile", explode)
    runner.limpar_cache_de_perfis()
    assert runner.fluxo_da_conversa({"agent_profile_id": "p1"}, {}) is None


def test_is_button_flow_conversation_segue_funcionando(monkeypatch):
    """Regressão: o processor da recuperação chama esta função hoje."""
    monkeypatch.setenv("RECUPERACAO_ENABLED", "on")
    monkeypatch.setattr(runner, "get_agent_profile",
                        lambda _id: {"kind": "button_flow", "flow_id": None})
    runner.limpar_cache_de_perfis()
    assert runner.is_button_flow_conversation({"agent_profile_id": "p1"}, {}) is True
```

- [ ] **Step 2: Rode e confirme que falha**

Run: `cd backend && python -m pytest tests/test_valeria_gate_2026_09_29.py -v`
Expected: FAIL — `enabled()` não aceita argumento; `fluxo_da_conversa` não existe.

- [ ] **Step 3: Implemente**

Em `config.py`, `enabled` passa a receber o fluxo, com um mapa explícito de fluxo → env var.
Mantenha a leitura crua de `os.getenv` a cada chamada, que é o que torna o kill switch
utilizável com um restart (está documentado no docstring do módulo):

```python
# Cada fluxo tem a SUA chave. Uma chave só fechava os dois: ligar a ValerIA de
# botões armaria a Recuperação junto — que está desligada e tem 3 bloqueantes.
_CHAVE_POR_FLUXO = {
    "recuperacao_v1": "RECUPERACAO_ENABLED",
    "valeria_botoes_v1": "VALERIA_BOTOES_ENABLED",
}


def enabled(flow_id: str) -> bool:
    """Kill switch POR FLUXO. Default OFF, e fluxo desconhecido é OFF.

    Fluxo desconhecido devolve False em vez de levantar: este gate roda em TODO
    inbound, e um flow_id novo gravado à mão num perfil não pode virar exceção no
    caminho da mensagem.
    """
    chave = _CHAVE_POR_FLUXO.get(flow_id)
    if not chave:
        return False
    return _env(chave, "off").lower() in _LIGADO
```

Em `runner.py`, `fluxo_da_conversa(conversation, channel) -> str | None` com a mesma
precedência e o mesmo fail-open do `is_button_flow_conversation` atual, e o cache passando a
guardar `(kind, flow_id)`. **Mantenha `is_button_flow_conversation` funcionando** — o
processor da recuperação a chama hoje; reescreva-a como
`return fluxo_da_conversa(...) == "recuperacao_v1"`.

**Se o processor chamar `is_button_flow_conversation` em mais lugares do que você
esperava, PARE e reporte antes de mudar a semântica.**

- [ ] **Step 4: Rode e confirme que passa**

Run: `cd backend && python -m pytest tests/test_valeria_gate_2026_09_29.py tests/test_button_flow_runner_2026_09_09.py tests/test_button_flow_disparo_2026_09_09.py -v`
Expected: PASS nos 11 novos **e** em toda a suíte do runner e do disparo da recuperação.

- [ ] **Step 5: Reporte ao orquestrador.** NÃO commite.

---

## Task 8: O runner da ValerIA (I/O)

**Files:**
- Create: `backend/app/button_flow/valeria_runner.py`
- Test: `backend/tests/test_valeria_runner_2026_09_29.py`

Depende das Tasks 1, 2, 5, 6. **Leia `backend/app/button_flow/runner.py` inteiro antes** —
este arquivo é o irmão dele e deve seguir a mesma divisão (montagem do evento, aplicação da
decisão, persistência do `flow_state`, efeitos) e reusar `button_flow/effects.py`.

- [ ] **Step 1: Escreva o teste que falha**

```python
"""O runner da ValerIA: monta o evento, aplica a decisão, envia e persiste.

Testado com dublês de provedor e de banco, como test_button_flow_runner_2026_09_09.py
já faz. O que importa aqui é o CONTRATO de envio (que método do provedor é chamado
para cada tipo de tela) e a persistência do contador de nudges.
"""
import pytest

from app.button_flow import valeria_registry as reg
from app.button_flow import valeria_runner as runner


class ProvedorFalso:
    def __init__(self):
        self.chamadas = []

    async def send_interactive_buttons(self, to, body, buttons, image_url=None):
        self.chamadas.append(("botoes", body, buttons, image_url))
        return {"messages": [{"id": "wamid.1"}]}

    async def send_interactive_list(self, to, body, button, rows, header=None):
        self.chamadas.append(("lista", body, rows))
        return {"messages": [{"id": "wamid.2"}]}

    async def send_text(self, to, text):
        self.chamadas.append(("texto", text))
        return {"messages": [{"id": "wamid.3"}]}


@pytest.mark.asyncio
async def test_no_de_lista_usa_send_interactive_list():
    p = ProvedorFalso()
    await runner.enviar_no(p, "5534988861441", reg.NOS["N0"], {})
    assert p.chamadas[0][0] == "lista"
    assert len(p.chamadas[0][2]) == 4, "N0 tem 4 linhas"


@pytest.mark.asyncio
async def test_no_de_botoes_usa_send_interactive_buttons_sem_imagem():
    p = ProvedorFalso()
    await runner.enviar_no(p, "5534988861441", reg.NOS["N1"], {})
    tipo, _body, botoes, image_url = p.chamadas[0]
    assert tipo == "botoes"
    assert len(botoes) == 3
    assert image_url is None


@pytest.mark.asyncio
async def test_no_de_foto_manda_UMA_mensagem_com_header():
    """Foto + preço + botões numa mensagem é o que corta 2 msgs faturadas por lead."""
    p = ProvedorFalso()
    await runner.enviar_no(p, "5534988861441", reg.NOS["N5"],
                           {"preco": "R$28,70"})
    assert len(p.chamadas) == 1, "não pode ser foto e depois texto"
    assert p.chamadas[0][3], "image_url não foi montado"


@pytest.mark.asyncio
async def test_sem_preco_no_catalogo_o_corpo_sai_sem_a_linha_de_preco():
    """Cotar de memória foi o que perdeu as 500 unidades da Ritz."""
    p = ProvedorFalso()
    await runner.enviar_no(p, "5534988861441", reg.NOS["N5"], {})
    corpo = p.chamadas[0][1]
    assert "{preco}" not in corpo, "marcador vazou para o lead"
    assert "R$" not in corpo, "cotou sem catálogo"


def test_estado_novo_comeca_na_entrada_com_zero_nudges():
    assert runner.estado_inicial() == {
        "flow": reg.FLOW_ID, "node": reg.NO_ENTRADA, "nudges": 0,
    }


def test_nudge_incrementa_e_clique_nao():
    assert runner.proximo_estado({"nudges": 1}, "N1", marcar_nudge=True)["nudges"] == 2
    assert runner.proximo_estado({"nudges": 1}, "N2", marcar_nudge=False)["nudges"] == 1


def test_estado_de_outro_fluxo_e_tratado_como_incompativel():
    """flow_state da recuperação não pode ser lido como se fosse da ValerIA."""
    assert runner.no_atual({"flow": "recuperacao_v1", "node": "aguardando_prazo"}) is None


# ── O score, que é o objetivo do ramo de atacado ──────────────────────────
@pytest.mark.asyncio
async def test_criterios_do_clique_viram_snapshot_de_score(monkeypatch):
    """Sem isto o ramo de atacado roda inteiro e não qualifica ninguém — que é
    exatamente o que o fluxo existe para consertar."""
    gravados = []
    monkeypatch.setattr(runner, "save_score_evidence",
                        lambda **kw: gravados.append(kw))
    await runner.aplicar_criterios("lead-1", {"segment": "cafeteria"})
    assert gravados, "save_score_evidence não foi chamado"
    assert gravados[0]["lead_id"] == "lead-1"
    assert gravados[0]["criteria"] == {"segment": "cafeteria"}


@pytest.mark.asyncio
async def test_criterios_vazios_nao_chamam_o_banco():
    """Nó sem `grava` (N5, os terminais) não pode gerar escrita por turno."""
    gravados = []
    await runner.aplicar_criterios("lead-1", {})
    assert gravados == []


@pytest.mark.asyncio
async def test_falha_do_score_nao_derruba_o_turno(monkeypatch):
    """O lead recebe a próxima tela mesmo que o snapshot falhe. Fail-open:
    perder um ponto de score é menos grave que deixar o lead sem resposta."""
    def explode(**_kw):
        raise RuntimeError("conflito de CAS")
    monkeypatch.setattr(runner, "save_score_evidence", explode)
    await runner.aplicar_criterios("lead-1", {"segment": "cafeteria"})
```

**Confira a assinatura real de `save_score_evidence`** em
`backend/app/lead_score/repository.py` antes de escrever o teste — ela recebe `source`
(`'live'` ou `'backfill'`) e pode levantar `ScoreWriteConflictError`. Se os nomes dos
parâmetros divergirem do teste acima, ajuste o TESTE para a assinatura real e reporte a
divergência.

- [ ] **Step 2: Rode e confirme que falha**

Run: `cd backend && python -m pytest tests/test_valeria_runner_2026_09_29.py -v`
Expected: FAIL — `ModuleNotFoundError: app.button_flow.valeria_runner`

- [ ] **Step 3: Implemente**

Funções públicas mínimas, na ordem em que o teste as exige: `estado_inicial()`,
`no_atual(estado)`, `proximo_estado(estado, node, marcar_nudge)`,
`enviar_no(provider, telefone, no, contexto)` e a entrada do gate,
`processar_inbound(...)`, no molde de `runner.py`.

Regras que o teste fixa e que não podem mudar:
- `tela == "lista"` → `send_interactive_list`; `"botoes"` → `send_interactive_buttons`;
  `"foto_botoes"` → `send_interactive_buttons` **com `image_url`** (uma mensagem, nunca duas).
- Sem preço resolvido no catálogo, a linha de preço **sai do corpo** — nem marcador, nem
  número inventado. Espelha `MSG_QUENTE_SEM_PRECO` de `flows.py`.
- `flow_state` com `flow` diferente de `FLOW_ID` é incompatível → `no_atual` devolve `None`
  e o chamador recomeça limpo.

- [ ] **Step 4: Rode e confirme que passa**

Run: `cd backend && python -m pytest tests/test_valeria_runner_2026_09_29.py -v`
Expected: PASS, 7 testes.

- [ ] **Step 5: Reporte ao orquestrador.** NÃO commite.

---

## Task 9: As rotas da API

**Files:**
- Create: `backend/app/button_flow/valeria_flow_router.py`
- Modify: `backend/app/main.py` (registrar o router)
- Test: `backend/tests/test_valeria_flow_router_2026_09_29.py`

Depende das Tasks 1 e 6. **Leia `backend/app/agent_profiles/router.py`** para o padrão de
`require_role(["admin"])` e o formato de resposta.

- [ ] **Step 1: Escreva o teste que falha**

```python
"""As 5 rotas de /api/valeria-flow.

A mescla registry+overrides acontece NO SERVIDOR: se a tela mesclasse, haveria duas
versões da regra de default, e divergência de default é a classe de bug que
campaigns/node_registry.py documenta.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.button_flow import valeria_registry as reg


@pytest.fixture
def cliente(monkeypatch):
    from app.auth import dependencies
    app.dependency_overrides[dependencies.require_role] = lambda _roles: (lambda: None)
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_get_devolve_os_nos_ja_mesclados(cliente, monkeypatch):
    from app.button_flow import valeria_content
    monkeypatch.setattr(valeria_content, "carregar",
                        lambda _f: {"N1": {"corpo": "editado"}})
    r = cliente.get("/api/valeria-flow")
    assert r.status_code == 200
    nos = {n["id"]: n for n in r.json()["nos"]}
    assert nos["N1"]["corpo"] == "editado"
    assert nos["N2"]["corpo"] == reg.NOS["N2"].corpo


def test_get_marca_o_que_foi_editado(cliente, monkeypatch):
    """A tela precisa oferecer 'restaurar o original' só onde há override."""
    from app.button_flow import valeria_content
    monkeypatch.setattr(valeria_content, "carregar",
                        lambda _f: {"N1": {"corpo": "editado"}})
    nos = {n["id"]: n for n in cliente.get("/api/valeria-flow").json()["nos"]}
    assert nos["N1"]["editado"] is True
    assert nos["N2"]["editado"] is False


def test_get_expoe_o_destino_como_leitura(cliente):
    nos = {n["id"]: n for n in cliente.get("/api/valeria-flow").json()["nos"]}
    botao = nos["N1"]["botoes"][0]
    assert botao["destino"] == "N2"
    assert botao["editavel"] is False or "destino" not in botao.get("editaveis", [])


def test_put_rejeita_rotulo_longo_com_400(cliente):
    r = cliente.put("/api/valeria-flow/N1",
                    json={"rotulos": {"cafeteria": "U" * 21}})
    assert r.status_code == 400
    assert "20" in r.json()["detail"]


def test_put_rejeita_corpo_vazio_com_400(cliente):
    assert cliente.put("/api/valeria-flow/N1", json={"corpo": "  "}).status_code == 400


def test_put_em_no_inexistente_da_404(cliente):
    assert cliente.put("/api/valeria-flow/NAO_EXISTE",
                       json={"corpo": "x"}).status_code == 404


def test_put_ignora_destino_no_payload(cliente):
    """Rota é estrutura. Nem por PUT se muda."""
    r = cliente.put("/api/valeria-flow/N1",
                    json={"corpo": "ok", "destino": "T_OPTOUT"})
    assert r.status_code in (200, 400)
    assert reg.NOS["N1"].botoes[0].destino == "N2"


def test_activate_recusa_canal_ausente(cliente):
    assert cliente.post("/api/valeria-flow/activate", json={}).status_code == 422
```

**Se `require_role` não puder ser sobrescrito por `dependency_overrides` desse jeito, PARE e
reporte** — confira como os outros testes de rota autenticada deste repo fazem
(`grep -rl "dependency_overrides" backend/tests/`) e siga o padrão existente.

- [ ] **Step 2: Rode e confirme que falha**

Run: `cd backend && python -m pytest tests/test_valeria_flow_router_2026_09_29.py -v`
Expected: FAIL — 404 em todas as rotas.

- [ ] **Step 3: Implemente**

| Rota | Comportamento |
|---|---|
| `GET /api/valeria-flow` | registry + `carregar()` já mesclados, com `editado: bool` por nó |
| `PUT /api/valeria-flow/{node_id}` | 404 se o nó não existe; 400 com a mensagem de `validar()`; grava `corpo`/`rotulos` e move o rótulo anterior para `rotulos_antigos` |
| `DELETE /api/valeria-flow/{node_id}` | apaga o override |
| `GET /api/valeria-flow/channels` | canais + perfil atual + `perfil_compartilhado: bool` |
| `POST /api/valeria-flow/activate` | cria perfil `kind='button_flow'`/`flow_id=FLOW_ID`, faz o `PATCH` do canal, chama `limpar_cache_de_perfis()` |

- [ ] **Step 4: Rode e confirme que passa**

Run: `cd backend && python -m pytest tests/test_valeria_flow_router_2026_09_29.py -v`
Expected: PASS, 8 testes.

- [ ] **Step 5: Reporte ao orquestrador.** NÃO commite.

---

## Task 10: Ligar no processor — SOZINHA, RISCO ALTO

**Files:**
- Modify: `backend/app/buffer/processor.py`
- Test: `backend/tests/test_valeria_processor_2026_09_29.py`

Este é o caminho de **todo inbound do backend**. Depende das Tasks 7 e 8.

**Leia primeiro** onde `is_button_flow_conversation` é chamada hoje no processor e como o
gate da recuperação se posiciona em relação ao gate de canal humano (há um comentário no
`config.py` dizendo que o gate do fluxo roda ANTES do gate de `mode='human'`, e por quê).

- [ ] **Step 1: Escreva o teste que falha**

```python
"""O roteamento do inbound: qual motor atende esta conversa.

O que este teste protege é o caso de erro, não o caminho felizes: com a chave
desligada, com perfil llm, ou com o banco fora, o inbound TEM que seguir para a
ValerIA LLM como sempre. Fail-closed aqui sequestraria conversa humana.
"""
import pytest

from app.buffer import processor


def test_chave_desligada_nao_roteia_para_botoes(monkeypatch):
    monkeypatch.delenv("VALERIA_BOTOES_ENABLED", raising=False)
    monkeypatch.setattr(processor, "fluxo_da_conversa", lambda *_a: None)
    assert processor.motor_do_inbound({"agent_profile_id": "p1"}, {}) == "llm"


def test_perfil_da_valeria_de_botoes_roteia_para_o_runner(monkeypatch):
    monkeypatch.setattr(processor, "fluxo_da_conversa", lambda *_a: "valeria_botoes_v1")
    assert processor.motor_do_inbound({"agent_profile_id": "p1"}, {}) == "valeria_botoes_v1"


def test_perfil_da_recuperacao_continua_indo_para_o_runner_dela(monkeypatch):
    monkeypatch.setattr(processor, "fluxo_da_conversa", lambda *_a: "recuperacao_v1")
    assert processor.motor_do_inbound({"agent_profile_id": "p1"}, {}) == "recuperacao_v1"


def test_erro_ao_resolver_cai_no_llm(monkeypatch):
    def explode(*_a):
        raise RuntimeError("banco fora")
    monkeypatch.setattr(processor, "fluxo_da_conversa", explode)
    assert processor.motor_do_inbound({"agent_profile_id": "p1"}, {}) == "llm"


def test_orchestrator_nao_e_chamado_no_fluxo_de_botoes(monkeypatch):
    """Zero IA não é só não usar o classificador: o orchestrator não roda."""
    chamou = []
    monkeypatch.setattr(processor, "fluxo_da_conversa", lambda *_a: "valeria_botoes_v1")
    monkeypatch.setattr(processor, "run_agent_turn",
                        lambda *a, **k: chamou.append(1))
    assert processor.motor_do_inbound({"agent_profile_id": "p1"}, {}) != "llm"
    assert chamou == []
```

**Se `processor.py` não expuser um ponto onde uma função `motor_do_inbound` pura caiba
naturalmente, PARE e reporte com o trecho relevante** em vez de refatorar o processor para
encaixar o teste. O objetivo é uma decisão testável, não uma reforma.

- [ ] **Step 2: Rode e confirme que falha**

Run: `cd backend && python -m pytest tests/test_valeria_processor_2026_09_29.py -v`
Expected: FAIL — `AttributeError: module 'app.buffer.processor' has no attribute 'motor_do_inbound'`

- [ ] **Step 3: Implemente**

Extraia a decisão para `motor_do_inbound(conversation, channel) -> str` (devolve `"llm"` ou
o `flow_id`), com `try/except` devolvendo `"llm"`. Ligue o despacho: `"valeria_botoes_v1"`
chama `valeria_runner.processar_inbound`, `"recuperacao_v1"` segue chamando o runner atual,
`"llm"` segue o caminho existente sem nenhuma mudança.

- [ ] **Step 4: Rode a suíte inteira do backend**

Run: `cd backend && python -m pytest tests/ -q`
Expected: PASS. Compare a contagem com a de antes da execução — **nenhum teste pode ter
passado a falhar**. Se algum falhar, reporte a saída completa e PARE.

- [ ] **Step 5: Reporte ao orquestrador.** NÃO commite.

---

# FASE B — O MODAL

## Task 11: Rotas proxy do frontend

**Files:**
- Create: `frontend/src/app/api/valeria-flow/route.ts`
- Create: `frontend/src/app/api/valeria-flow/[nodeId]/route.ts`
- Create: `frontend/src/app/api/valeria-flow/channels/route.ts`
- Create: `frontend/src/app/api/valeria-flow/activate/route.ts`

**Leia `frontend/src/app/api/agent-profiles/route.ts` e copie o padrão de proxy** (como a
URL do backend é resolvida, como o erro é propagado, como o auth é repassado). Não invente
um padrão novo.

- [ ] **Step 1: Implemente os 4 proxies** seguindo exatamente o padrão do arquivo lido.
- [ ] **Step 2: Rode o typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: sem erro nos arquivos novos.

- [ ] **Step 3: Reporte ao orquestrador.** NÃO commite.

---

## Task 12: O shell do modal

**Files:**
- Create: `frontend/src/components/campaigns/valeria-flow-modal.tsx`
- Create: `frontend/src/components/campaigns/valeria-flow-modal.test.tsx`

**REQUIRED: invoque a skill `frontend-design` antes de escrever o componente.** É regra
registrada do usuário. E **leia `valeria-score-modal.tsx`** — o modal irmão em `/campanhas`,
cujo estilo (densidade, `useState` numa linha, tratamento de erro) deve ser espelhado.

O shell tem: overlay, duas abas (`Fluxo` e `Onde está ativo`), o `fetch` do
`GET /api/valeria-flow` com `AbortController`, e o estado compartilhado. Os dois painéis
entram como componentes das Tasks 13 e 14 — declare as props e renderize um placeholder
que as Tasks 13/14 substituem.

- [ ] **Step 1** Escreva o teste do shell (troca de aba, estado de carregando, propagação de erro).
- [ ] **Step 2** `cd frontend && npx vitest run src/components/campaigns/valeria-flow-modal.test.tsx` — **se `@testing-library` ou `jsdom` não estiverem instalados, PARE e reporte**: eles estão ausentes do `node_modules` deste repo (registrado em duas memórias) e instalar é decisão do usuário.
- [ ] **Step 3** Implemente o shell.
- [ ] **Step 4** Rode o teste e o `npx tsc --noEmit`.
- [ ] **Step 5: Reporte ao orquestrador.** NÃO commite.

---

## Task 13: O editor + preview de WhatsApp

**Files:**
- Create: `frontend/src/components/campaigns/valeria-flow-editor.tsx`
- Create: `frontend/src/components/campaigns/valeria-flow-editor.test.tsx`

**REQUIRED: invoque `frontend-design` antes.** Depende da Task 12.

Três colunas: ramos → nós do ramo → editor. O editor tem o textarea do corpo, um input por
rótulo com **contador de caracteres e o limite da Meta visível**, e o **preview da bolha do
WhatsApp ao lado**, atualizando a cada tecla. O preview é o que torna o modal usável por
quem não lê código; o visual de referência é o artefato aprovado
`https://claude.ai/artifact/J3t1jxSQRhHCfMHLSm7zdG`.

O destino de cada botão aparece como leitura (`→ N2`) e **não é editável**.

- [ ] **Step 1** Teste: contador bloqueia salvar acima do limite; preview reflete a edição; "restaurar o original" só aparece em nó editado; destino não tem input.
- [ ] **Step 2** Rode e confirme que falha.
- [ ] **Step 3** Implemente.
- [ ] **Step 4** Rode teste + `npx tsc --noEmit`.
- [ ] **Step 5: Reporte ao orquestrador.** NÃO commite.

---

## Task 14: A aba "Onde está ativo"

**Files:**
- Create: `frontend/src/components/campaigns/valeria-flow-channels.tsx`
- Create: `frontend/src/components/campaigns/valeria-flow-channels.test.tsx`

**REQUIRED: invoque `frontend-design` antes.** Depende da Task 12.

Lista os canais com o perfil atual e o botão "Ativar a Valéria de botões neste canal". O
aviso de **perfil compartilhado** é obrigatório e não decorativo: os canais da ValerIA
(`674beb13`) e do João (`a3a607b1`) apontam para o mesmo `agent_profile_id`, verificado em
produção, e é por isso que "Ativar" cria perfil novo em vez de editar o existente.

- [ ] **Step 1** Teste: aviso aparece quando `perfil_compartilhado` é true; "Ativar" chama `POST /activate` com o `channel_id`; erro da rota vira mensagem na tela.
- [ ] **Step 2** Rode e confirme que falha.
- [ ] **Step 3** Implemente.
- [ ] **Step 4** Rode teste + `npx tsc --noEmit`.
- [ ] **Step 5: Reporte ao orquestrador.** NÃO commite.

---

## Task 15: O botão em `/campanhas`

**Files:**
- Modify: `frontend/src/app/(authenticated)/campanhas/page.tsx`

Espelhe exatamente o que `page.tsx:196` faz com o `ValeriaScoreModal`: um
`useState(false)`, um botão no header ao lado do de Score, e o componente no fim do JSX.

- [ ] **Step 1** Adicione `showValeriaFlowModal`, o botão "Fluxo da Valéria" e o `<ValeriaFlowModal>`.
- [ ] **Step 2** `cd frontend && npx tsc --noEmit` — sem erro.
- [ ] **Step 3: Reporte ao orquestrador.** NÃO commite.

---

## Verificação final (orquestrador, não subagente)

- [ ] `cd backend && python -m pytest tests/ -q` — contagem comparada com a do início
- [ ] `cd frontend && npx tsc --noEmit`
- [ ] `git status --short` — nada staged que não seja desta feature
- [ ] `git log --oneline origin/master..HEAD` — só commits desta feature
- [ ] **A migration NÃO foi aplicada.** Ela é pré-requisito do modal e do "Ativar", não do
      código subir. Avisar o usuário explicitamente.
- [ ] **`VALERIA_BOTOES_ENABLED` não está no `.env`.** Default off. Ligar é decisão do
      usuário, depois de validar em navegador.
