"""Cria os 4 templates do agente de Recuperacao na WABA, via Meta Graph API.

Dry-run por padrao. So escreve na Meta com --apply.

── Por que estes textos e nao outros (09/09/2026) ────────────────────────────
Cada decisao aqui saiu de medicao sobre ~1.300 envios reais desta conta:

1. **pt_BR, nao en_US.** O folclore de que en_US aprova mais facil e falso: entre
   os 28 templates que a Meta reclassificou de UTILITY p/ MARKETING nesta conta ha
   13 pt_BR e 15 en_US — mesma proporcao.

2. **Nome sem a substring "reativ".** `_hot_lead_guardrail` (broadcast/worker.py
   ~991-1022), disparado por `_COLD_SUBSTRINGS = ("reativ",)` em
   templates/intent.py:22-23, rejeita silenciosamente qualquer lead com venda em
   `sales` quando o nome do template casa. 208 dos 1.208 leads da coorte tem venda
   em `sales` — exatamente a parte mais valiosa da lista.

3. **3 botoes, nunca mais.** A partir de 4, o WhatsApp Desktop nao renderiza os
   botoes — e a coorte e 97,2% B2B (1.174 de 1.208 com CNPJ), gente que responde do
   PC do balcao.

4. **Rotulos <= 20 chars**, embora o template aceite 25: assim o MESMO texto serve
   no template e na mensagem interativa do reoferecimento (cujo limite e 20), e o
   motor casa o clique nas duas superficies.

5. **Pergunta de ESTADO, nao de COMPROMISSO.** "Falo com {{1}} neste numero?" teve
   33,5% de resposta e 74% de positivos; "pedido em aberto, continuar?" teve 8,6%.

6. **Terceiro slot e saida de verdade.** "Parar mensagens" e o rotulo dos 2
   templates aprovados mais recentes desta conta (27/08). O antigo "Nao tenho
   interesse" era ambiguo: 64 cliques, e 41% dessas pessoas continuaram conversando.

7. **Sem oferta, desconto, cupom, prazo ou urgencia no corpo.** Regra empirica
   extraida dos 28 recategorizados: o que sobreviveu como UTILITY ancora num fato
   concreto e verificavel da conta do cliente; o que virou MARKETING prometia
   continuidade vaga ("de onde paramos") ou prazo ("ate {{3}}" — 3 de 3 caíram).

8. **Sem instrucao textual de opt-out no footer.** Foi o que reprovou
   `claude_test_004` por INVALID_FORMAT. O botao ja e a saida.

A categoria pedida aqui e a HONESTA para cada corpo; a Meta pode reclassificar, e o
orcamento da campanha ja assume MARKETING de qualquer forma (spec, decisao D3).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://graph.facebook.com/v21.0"

# Rotulos: precisam casar BYTE A BYTE com flows.BOTOES_POR_TRILHA, senao o preflight
# do disparo reprova e o casamento de clique quebra.
BTN_PARAR = {"type": "QUICK_REPLY", "text": "Parar mensagens"}


def _body(texto: str, exemplos: list[str]) -> dict:
    return {"type": "BODY", "text": texto, "example": {"body_text": [exemplos]}}


def _botoes(*textos: str) -> dict:
    return {"type": "BUTTONS",
            "buttons": [{"type": "QUICK_REPLY", "text": t} for t in textos] + [BTN_PARAR]}


TEMPLATES = [
    # ── T-A · trilha "pedido" (pedido_sem_faturar, 62 leads) ─────────────────
    # UTILITY e honesta aqui: existe um pedido real e pendente no Bling, e
    # produto_top1 esta preenchido em 62/62 desses leads.
    {
        "name": "recuperacao_pedido_v1",
        "language": "pt_BR",
        "category": "UTILITY",
        "components": [
            _body(
                "Olá, {{1}}! Aqui é o João, do Café Canastra.\n"
                "Consta no nosso sistema um pedido seu de {{2}} que não chegou a ser "
                "faturado, e ninguém te retornou depois disso.\n"
                "Quer que eu retome esse pedido de onde parou?",
                ["Carlos", "Café Canastra Clássico Moído 250g"],
            ),
            _botoes("Retomar o pedido", "Quero outro item"),
        ],
    },
    # ── T-B · trilha "estoque" (inativos 3-36m, 303 leads) ───────────────────
    # MARKETING assumida. Carrega as duas alavancas maiores de uma vez: memoria
    # concreta (o vendedor cita historico em apenas 10 msgs no dataset inteiro, e
    # sempre fecha quando cita) e pergunta de estado de baixo compromisso.
    {
        "name": "recuperacao_estoque_v1",
        "language": "pt_BR",
        "category": "MARKETING",
        "components": [
            _body(
                "Olá, {{1}}! Aqui é o João, do Café Canastra.\n"
                "Vi aqui no cadastro que a última compra da {{2}} com a gente foi em "
                "{{3}} — {{4}}.\n"
                "Como está o estoque de café por aí hoje?",
                ["Ana", "Empório Sabor da Serra", "março de 2026",
                 "Café Canastra Suave em Grãos 1kg"],
            ),
            _botoes("Preciso repor", "Ainda tenho estoque"),
        ],
    },
    # ── T-C · trilha "cadastro" (inativo_36m_mais, 665 leads) ────────────────
    # UTILITY e honesta porque este corpo NAO VENDE. Compraram ha 3 a 7 anos; um
    # legitimo interesse honesto nao sustenta marketing para essa faixa. Quem clicar
    # "Manter cadastro" vira opt-in prospectivo registrado e entra na trilha
    # comercial numa SEGUNDA campanha. Modelado em
    # `utilidade_joao_cadastro_movimentacao`, que segue UTILITY na Meta ate hoje.
    {
        "name": "recuperacao_cadastro_v1",
        "language": "pt_BR",
        "category": "UTILITY",
        "components": [
            _body(
                "Olá, {{1}}! Aqui é o João, do Café Canastra.\n"
                "Estamos atualizando nosso cadastro de clientes e o da {{2}} consta "
                "sem movimentação desde {{3}}.\n"
                "Seguimos mantendo seu contato ativo por aqui?",
                ["Marcos", "Mercado Bom Preço", "agosto de 2022"],
            ),
            _botoes("Manter cadastro", "Atualizar dados"),
        ],
    },
    # ── T-D · toque D+4 para quem nao respondeu nada ─────────────────────────
    # Nome diferente e OBRIGATORIO: `_template_dedup_guardrail`
    # (broadcast/worker.py ~1025-1062, BROADCAST_TEMPLATE_DEDUP_DAYS=14) pularia
    # em silencio um reenvio do mesmo template_name para o mesmo lead.
    {
        "name": "recuperacao_lembrete_v1",
        "language": "pt_BR",
        "category": "MARKETING",
        "components": [
            _body(
                "Olá, {{1}}! Ainda é o João, do Café Canastra.\n"
                "Minha mensagem de {{2}} ficou sem resposta e não quero te incomodar "
                "à toa.\n"
                "Me dá só um sinal pra eu saber como seguir?",
                ["Ana", "terça-feira"],
            ),
            _botoes("Preciso repor", "Ainda tenho estoque"),
        ],
    },
]


def _carregar_env() -> tuple[str, str]:
    waba = os.environ.get("META_WABA_ID", "")
    token = os.environ.get("META_ACCESS_TOKEN", "")
    if waba and token:
        return waba, token
    # Conveniencia de dev: le do .env.local sem exportar nada no shell.
    env_path = Path(__file__).resolve().parents[2] / "backend" / ".env.local"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            chave, valor = line.split("=", 1)
            if chave.strip() == "META_WABA_ID" and not waba:
                waba = valor.strip()
            elif chave.strip() == "META_ACCESS_TOKEN" and not token:
                token = valor.strip()
    if not waba or not token:
        sys.exit("META_WABA_ID e META_ACCESS_TOKEN nao encontrados (env nem backend/.env.local)")
    return waba, token


def _existentes(waba: str, token: str) -> dict[str, dict]:
    url = f"{API}/{waba}/message_templates?limit=200&fields=name,status,category,language"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        dados = json.loads(resp.read())
    return {t["name"]: t for t in dados.get("data", [])}


def _validar(tpl: dict) -> list[str]:
    """Checagens que a Meta faria — mas errar aqui custa uma reprovacao no historico."""
    erros: list[str] = []
    botoes = next((c for c in tpl["components"] if c["type"] == "BUTTONS"), None)
    if not botoes:
        erros.append("sem componente BUTTONS")
    else:
        if len(botoes["buttons"]) != 3:
            erros.append(f"{len(botoes['buttons'])} botoes (o desenho exige exatamente 3)")
        for b in botoes["buttons"]:
            # 20 e o limite da INTERATIVA, mais apertado que os 25 do template. Usamos
            # o menor para que o mesmo rotulo sirva nas duas superficies.
            if len(b["text"]) > 20:
                erros.append(f"rotulo {b['text']!r} tem {len(b['text'])} chars (max 20)")
    corpo = next((c for c in tpl["components"] if c["type"] == "BODY"), None)
    if not corpo:
        erros.append("sem componente BODY")
    else:
        n_vars = corpo["text"].count("{{")
        n_ex = len(corpo["example"]["body_text"][0])
        if n_vars != n_ex:
            erros.append(f"{n_vars} variaveis mas {n_ex} exemplos (erro #132000)")
        if len(corpo["text"]) > 1024:
            erros.append(f"corpo com {len(corpo['text'])} chars (max 1024)")
    if "reativ" in tpl["name"]:
        erros.append("nome contem 'reativ' — cai na TRAVA A e bloqueia os 208 melhores leads")
    return erros


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="cria de verdade na Meta (sem isso, so mostra o que faria)")
    args = ap.parse_args()

    waba, token = _carregar_env()
    ja_existem = _existentes(waba, token)

    problemas = False
    for tpl in TEMPLATES:
        erros = _validar(tpl)
        marca = "JA EXISTE" if tpl["name"] in ja_existem else "novo"
        print(f"\n=== {tpl['name']} [{tpl['category']}/{tpl['language']}] ({marca})")
        corpo = next(c for c in tpl["components"] if c["type"] == "BODY")
        print(corpo["text"])
        botoes = next(c for c in tpl["components"] if c["type"] == "BUTTONS")
        print("  botoes: " + " | ".join(f"[{b['text']}] ({len(b['text'])})"
                                        for b in botoes["buttons"]))
        if erros:
            problemas = True
            for e in erros:
                print(f"  !! {e}")
        if tpl["name"] in ja_existem:
            print(f"  -> status atual na Meta: {ja_existem[tpl['name']]['status']}")

    if problemas:
        sys.exit("\nABORTADO: corrija os problemas acima antes de criar.")

    if not args.apply:
        print("\n(dry-run — nada foi criado. Use --apply para criar de verdade.)")
        return

    url = f"{API}/{waba}/message_templates"
    for tpl in TEMPLATES:
        if tpl["name"] in ja_existem:
            print(f"pulando {tpl['name']} (ja existe)")
            continue
        payload = json.dumps(tpl, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url, data=payload, method="POST",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                res = json.loads(resp.read())
            print(f"OK  {tpl['name']} -> id={res.get('id')} status={res.get('status')} "
                  f"category={res.get('category')}")
        except urllib.error.HTTPError as exc:
            print(f"ERRO {tpl['name']}: {exc.code} {exc.read().decode()[:600]}")
        time.sleep(2)


if __name__ == "__main__":
    main()
