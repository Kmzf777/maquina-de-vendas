# -*- coding: utf-8 -*-
"""Conserta os 3 templates que foram para a Meta com o texto corrompido em 25/05/2026.

DOIS defeitos em cada um, nao um:

1. ACENTO PERDIDO. Os corpos chegaram a Meta com bytes U+003F no lugar dos acentos
   ("Ol? {{1}}, aqui ? o Jo?o da Caf? Canastra ?") — zero caracteres nao-ASCII no
   corpo, ou seja, corrupcao GRAVADA, nao problema de console. Causa: serializacao que
   passou por cp1252. Aqui o payload sai com `ensure_ascii=True` (ASCII puro, acentos
   como escape), o que torna a falha impossivel de repetir.

2. BOTAO DE SAIDA MORTO — mais grave que o acento, e ninguem tinha visto.
   `campaigns/worker.py::is_optout_reply` compara por IGUALDADE normalizada contra um
   frozenset de exatamente duas frases: {"nao tenho interesse", "parar mensagens"}.
   Os rotulos usados nos tres estao TODOS fora dele:

       check_estoque_reposicao        "Nao atendo mais"           -> morto
       lembrete_reposicao_final       "Tirar dos contatos"        -> morto
       continuidade_cotacao_pendente  "Nao tenho mais interesse"  -> morto (o "mais"!)

   Botao morto significa: o lead aperta o botao pedindo para sair, o sistema cancela o
   enrollment e nada mais acontece — sem `leads.opt_out`, sem funil Blacklist, sem
   cancelar follow-up. Dias depois ele e reinscrito e recebe tudo de novo. E o pior
   resultado possivel para o rating do numero, porque o proximo passo do lead e o
   botao "Bloquear" do WhatsApp.

A spec de 09/09 (`2026-09-09-valeria-recuperacao-botoes-design.md:231`) concluiu que
esses templates "nao sao editaveis; teriam de ser recriados". Isso foi verificado e e
FALSO: `POST /{template_id}` com novos `components` e aceito para template APPROVED,
devolve `success: true` e recoloca o template em PENDING para nova revisao. Manter o
NOME e o que importa — as campanhas `Follow-up Cotacao - Joao` e `Reposicao
Inteligente - Joao` referenciam esses nomes e nao precisam ser tocadas.

DOIS LIMITES DA META, os dois descobertos na pratica em 13/09/2026:

  a) So da para editar template em APPROVED, REJECTED ou PAUSED. Um template que acabou
     de ser editado fica PENDING e recusa nova edicao ate a revisao terminar.
  b) UMA EDICAO A CADA 24 HORAS por template ativo (erro 100, subcode 2388124,
     "Voce so pode editar um modelo ativo uma vez a cada 24 horas"). Consequencia
     pratica: NAO edite em duas etapas. Mande corpo e botoes na MESMA chamada, senao a
     segunda correcao fica trancada por um dia — foi exatamente o que aconteceu com
     `check_estoque_reposicao`, editado primeiro so para restaurar o acento e por isso
     impedido de receber a troca do botao morto no mesmo dia.

O script e idempotente: rodar de novo so reaplica o que ainda faltava.

Uso:
    python scripts/fix_templates_corrompidos.py            # mostra o que faria
    python scripts/fix_templates_corrompidos.py --aplicar
"""
import json
import os
import sys
import urllib.error
import urllib.request

WABA_ID = os.environ.get("META_WABA_ID")
TOKEN = os.environ.get("META_ACCESS_TOKEN")

FOOTER = {"type": "FOOTER", "text": "João | Café Canastra"}


def _botoes(*rotulos):
    return {"type": "BUTTONS",
            "buttons": [{"type": "QUICK_REPLY", "text": r} for r in rotulos]}


def _body(texto):
    return {"type": "BODY", "text": texto, "example": {"body_text": [["Marcella"]]}}


# Corpos restaurados a partir da INTENCAO ORIGINAL registrada em
# docs/superpowers/specs/2026-05-25-cadencias-joao-reposicao-inteligente-design.md,
# com o ultimo botao trocado por uma das duas frases que o sistema reconhece.
CORRECOES = [
    {
        "nome": "check_estoque_reposicao",
        "components": [
            _body("Olá {{1}}, aqui é o João da Café Canastra ☕\n\n"
                  "Você estava nos meus contatos de reposição em nosso sistema.\n"
                  "Como está seu estoque atual?"),
            FOOTER,
            # era: "Não atendo mais" (morto)
            _botoes("Preciso repor", "Ainda tenho estoque", "Parar mensagens"),
        ],
    },
    {
        "nome": "lembrete_reposicao_final",
        "components": [
            _body("Olá {{1}}, ainda é o João do Café Canastra.\n\n"
                  "Notei que minha mensagem anterior ficou sem resposta. Me dá só um "
                  "sinal de positivo ou negativo para eu saber como prosseguir, por "
                  "favor."),
            FOOTER,
            # era: "Tirar dos contatos" (morto)
            _botoes("Quero conversar", "Agora não", "Parar mensagens"),
        ],
    },
    {
        "nome": "continuidade_cotacao_pendente",
        "components": [
            _body("Olá {{1}}, aqui é o João da Café Canastra.\n\n"
                  "Sua solicitação de cotação está em aberto em nosso sistema há {{2}} "
                  "dias.\nConfirme se ainda deseja prosseguir com o atendimento."),
            FOOTER,
            # era: "Não tenho mais interesse" (morto por causa do "mais")
            _botoes("Sim, vamos prosseguir", "Tirar dúvidas antes", "Não tenho interesse"),
        ],
    },
]

# `continuidade_cotacao_pendente` tem DUAS variaveis ({{1}} nome, {{2}} dias) — o
# example precisa refletir isso ou a Meta recusa.
CORRECOES[2]["components"][0]["example"] = {"body_text": [["Marcella", "3"]]}


def _chamar(url, payload=None):
    dados = json.dumps(payload, ensure_ascii=True).encode("ascii") if payload else None
    req = urllib.request.Request(url, data=dados, method="POST" if dados else "GET")
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"__erro__": json.loads(e.read().decode("utf-8"))}


def _ja_esta_certo(atual, desejado):
    """True quando corpo e botoes ja batem — evita gastar a cota de edicao de 24h.

    Sem isto, rodar o script de novo reenvia os tres e queima o limite dos que ja
    estavam corretos, deixando-os travados por um dia caso surja uma correcao de
    verdade. A comparacao e so de corpo e rotulos: e o que este script muda.
    """
    def resumo(componentes):
        corpo = next((c.get("text") for c in componentes if c["type"] == "BODY"), None)
        botoes = [b.get("text") for c in componentes if c["type"] == "BUTTONS"
                  for b in c.get("buttons", [])]
        return corpo, botoes

    return resumo(atual) == resumo(desejado)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if not WABA_ID or not TOKEN:
        print("Defina META_WABA_ID e META_ACCESS_TOKEN no ambiente.")
        return 1

    atuais = {}
    url = (f"https://graph.facebook.com/v21.0/{WABA_ID}/message_templates"
           f"?limit=200&fields=id,name,status,category,components")
    while url:
        r = _chamar(url)
        if "__erro__" in r:
            print("Falha ao listar:", r)
            return 1
        for t in r.get("data", []):
            atuais[t["name"]] = t
        url = (r.get("paging") or {}).get("next")

    aplicar = "--aplicar" in sys.argv
    for c in CORRECOES:
        alvo = atuais.get(c["nome"])
        if not alvo:
            print(f"PULADO  {c['nome']}: nao existe na WABA")
            continue
        if _ja_esta_certo(alvo.get("components") or [], c["components"]):
            print(f"OK      {c['nome']}: ja esta correto, nada a fazer")
            continue
        if not aplicar:
            print(f"(dry-run) {c['nome']} [{alvo['status']}] -> corpo restaurado + "
                  f"botao de saida trocado")
            continue
        if alvo["status"] == "PENDING":
            print(f"PULADO  {c['nome']}: em PENDING, a Meta recusa editar agora. "
                  f"Rode de novo apos a revisao.")
            continue
        r = _chamar(f"https://graph.facebook.com/v21.0/{alvo['id']}",
                    {"components": c["components"]})
        print(("OK   " if r.get("success") else "ERRO ") + c["nome"] + ": " + str(r))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
