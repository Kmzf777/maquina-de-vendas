# -*- coding: utf-8 -*-
"""Submete na Meta os 24 templates das 6 esteiras do vendedor Joao.

Um template por NO DE ENVIO de `app/campaigns/esteiras_joao.py` — 1 toque na esteira
"Novo", 7 em "Em conversa" e 4 em "Reposicao", vezes as duas linhas (Atacado e Private
Label). Nenhum texto se repete: o motor de cadencias NAO tem o guardrail de dedup por
(lead, template) que o `broadcast/worker.py` tem, entao reaproveitar um nome faria o
mesmo texto sair duas vezes para o mesmo lead sem ninguem barrar.

--------------------------------------------------------------------------------
TRES REGRAS QUE ESTE ARQUIVO EXISTE PARA NAO DEIXAR QUEBRAR
--------------------------------------------------------------------------------

1. ENCODING (`ensure_ascii=True`).
   Em 25/05/2026 tres templates foram submetidos com os acentos ja perdidos e a
   corrupcao ficou GRAVADA na Meta: `check_estoque_reposicao` chegou a producao como
   "Ol? {{1}}, aqui ? o Jo?o da Caf? Canastra ?" — bytes U+003F, zero caracteres
   nao-ASCII no corpo. Aqui o JSON sai em ASCII puro, com cada acento como escape de
   6 caracteres. Nao existe byte >127 no fio, logo nao existe caminho para um acento
   virar '?'. `_auditar` aborta antes de submeter se algum corpo ja chegar corrompido.

2. O BOTAO DE SAIDA PRECISA SER UMA DAS DUAS FRASES QUE O SISTEMA RECONHECE.
   `campaigns/worker.py::_OPTOUT_REPLY_LABELS` e um frozenset com exatamente
   {"nao tenho interesse", "parar mensagens"} e o casamento e IGUALDADE normalizada,
   nunca substring. Rotulo fora dessas duas frases e um BOTAO MORTO: o lead aperta
   "pedindo para sair" e o sistema so cancela o enrollment — sem `leads.opt_out`, sem
   funil Blacklist. Foi o que aconteceu com "Nao atendo mais"
   (`check_estoque_reposicao`) e "Tirar dos contatos" (`lembrete_reposicao_final`).
   `_auditar` recusa qualquer template cujo ultimo botao nao seja reconhecido.

3. UMA VARIAVEL SO: {{1}} = primeiro nome.
   O motor preenche via `template_variables={"__params_type__":"positional",
   "1":"{{primeiro_nome}}"}` (`broadcast/worker.py::_build_template_components`).
   Medido em producao: 1.632 dos 1.731 cards dos funis do Joao (94,3%) tem nome
   utilizavel; nos outros ~5% `_lead_first_name` devolve "voce". Por isso o nome NUNCA
   abre a frase sozinho em vocativo — os corpos usam "Oi {{1}}," que degrada para
   "Oi voce," (esquisito, nao quebrado), e o nome do vendedor vai HARDCODED no texto
   em vez de virar um {{2}}: menos variavel, menos ponto de falha em runtime.

CATEGORIA: todos MARKETING, de proposito. Sao mensagens de reengajamento com fim
comercial; pedir UTILITY convida a re-categorizacao da Meta (foi o que aconteceu com
`check_estoque_reposicao` e `lembrete_reposicao_final`, submetidos como utility e hoje
MARKETING). Mais importante: o opt-out de marketing do WhatsApp e POR CATEGORIA — uma
esteira com categorias misturadas entregaria alguns toques e silenciaria outros para o
mesmo lead. Categoria unica mantem o comportamento previsivel.

Uso:
    python scripts/create_templates_esteiras_joao.py            # audita e mostra
    python scripts/create_templates_esteiras_joao.py --submeter # envia para a Meta
"""
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

WABA_ID = os.environ.get("META_WABA_ID")
TOKEN = os.environ.get("META_ACCESS_TOKEN")

FOOTER = {"type": "FOOTER", "text": "João | Café Canastra"}

# As DUAS unicas frases que `campaigns/worker.py::is_optout_reply` reconhece.
SAIDA_INTERESSE = "Não tenho interesse"
SAIDA_PARAR = "Parar mensagens"
SAIDAS_VALIDAS = {"nao tenho interesse", "parar mensagens"}


def _botoes(*rotulos):
    return {"type": "BUTTONS",
            "buttons": [{"type": "QUICK_REPLY", "text": r} for r in rotulos]}


def _tpl(nome, corpo, botoes):
    return {
        "name": nome,
        "language": "pt_BR",
        "category": "MARKETING",
        "components": [
            {"type": "BODY", "text": corpo, "example": {"body_text": [["Marcella"]]}},
            FOOTER,
            botoes,
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# ESTEIRA "NOVO" — 1 toque, card parado 2 dias na etapa 'novo'. Nao move o card.
# ─────────────────────────────────────────────────────────────────────────────
NOVO = [
    _tpl(
        "joao_novo_atacado_t1",
        "Oi {{1}}, aqui é o João, do Café Canastra.\n\n"
        "Vi que você chegou até nós interessado no nosso café para revenda, mas a "
        "nossa conversa acabou parando antes de eu conseguir te ajudar.\n\n"
        "Se quiser, te passo a tabela e as condições para o seu volume. Como prefere "
        "seguir?",
        _botoes("Quero ver a tabela", "Tirar uma dúvida", SAIDA_INTERESSE),
    ),
    _tpl(
        "joao_novo_privatelabel_t1",
        "Oi {{1}}, aqui é o João, do Café Canastra.\n\n"
        "Vi que você chegou até nós para falar sobre ter um café com a sua própria "
        "marca, mas a nossa conversa acabou parando antes de eu conseguir te ajudar."
        "\n\nSe quiser, te explico como funciona: quantidade mínima, prazo e o que "
        "precisamos da sua parte. Como prefere seguir?",
        _botoes("Quero entender", "Tirar uma dúvida", SAIDA_INTERESSE),
    ),
]

# ─────────────────────────────────────────────────────────────────────────────
# ESTEIRA "EM CONVERSA" — 7 toques em 30 dias (D+2/4/7/12/18/24/30).
# Arco: duvida -> valor -> prova social -> tirar atrito -> pergunta direta ->
# motivo concreto -> despedida digna. Qualquer resposta rebobina para D+0
# (on_reply='reset'), entao cada toque precisa funcionar como primeiro contato.
# ─────────────────────────────────────────────────────────────────────────────
EM_CONVERSA_ATACADO = [
    _tpl(
        "joao_conversa_atacado_t1",
        "Oi {{1}}, aqui é o João, do Café Canastra.\n\n"
        "A nossa conversa parou no meio e fiquei na dúvida se faltou alguma "
        "informação da minha parte.\n\n"
        "Ficou alguma pergunta sobre valores, prazo ou entrega?",
        _botoes("Ficou uma dúvida", "Me chama depois", SAIDA_INTERESSE),
    ),
    _tpl(
        "joao_conversa_atacado_t2",
        "Oi {{1}}, é o João do Café Canastra de novo.\n\n"
        "Só para você ter em mente: o nosso café é colhido e torrado na nossa "
        "fazenda, na Serra da Canastra, e sai daqui direto para o seu balcão, sem "
        "atravessador no meio.\n\n"
        "É isso que segura o preço e mantém o lote regular o ano inteiro. Faz sentido "
        "para a sua operação?",
        _botoes("Faz sentido", "Tenho uma dúvida", SAIDA_INTERESSE),
    ),
    _tpl(
        "joao_conversa_atacado_t3",
        "Oi {{1}}, aqui é o João, do Café Canastra.\n\n"
        "Boa parte das cafeterias que eu atendo começou com um volume pequeno, testou "
        "a aceitação com os próprios clientes e foi subindo a partir dali.\n\n"
        "Se preferir, monto uma primeira remessa nesse formato para você avaliar sem "
        "se comprometer com volume grande.",
        _botoes("Quero avaliar", "Tenho uma dúvida", SAIDA_INTERESSE),
    ),
    _tpl(
        "joao_conversa_atacado_t4",
        "Oi {{1}}, João aqui.\n\n"
        "Não quero te tomar tempo com conversa longa. Me diz só quantos quilos de "
        "café você usa por mês, mais ou menos, que eu já te devolvo a condição "
        "fechada para esse volume.",
        _botoes("Vou te passar", "Prefiro falar depois", SAIDA_INTERESSE),
    ),
    _tpl(
        "joao_conversa_atacado_t5",
        "Oi {{1}}, aqui é o João, do Café Canastra.\n\n"
        "Faz um tempo que a gente não conversa e eu não sei se o assunto do café "
        "ainda está de pé aí.\n\n"
        "Me dá um sinal para eu saber se sigo te procurando ou se deixo para mais "
        "para a frente?",
        _botoes("Ainda está de pé", "Deixa para depois", SAIDA_INTERESSE),
    ),
    _tpl(
        "joao_conversa_atacado_t6",
        "Oi {{1}}, é o João do Café Canastra.\n\n"
        "Entrou lote novo da safra aqui na fazenda e as condições mudaram um pouco em "
        "relação ao que a gente tinha conversado.\n\n"
        "Quer que eu te mande a tabela atualizada?",
        _botoes("Quero a tabela", "Agora não", SAIDA_INTERESSE),
    ),
    _tpl(
        "joao_conversa_atacado_t7",
        "Oi {{1}}, aqui é o João, do Café Canastra.\n\n"
        "Vou parar de te procurar por aqui para não virar incômodo.\n\n"
        "Se um dia o café entrar na sua lista, é só me chamar neste mesmo número. "
        "Fico à disposição e sem pressa.",
        _botoes("Quero retomar agora", SAIDA_INTERESSE),
    ),
]

EM_CONVERSA_PRIVATE_LABEL = [
    _tpl(
        "joao_conversa_privatelabel_t1",
        "Oi {{1}}, aqui é o João, do Café Canastra.\n\n"
        "A nossa conversa sobre o café com a sua marca parou no meio e fiquei na "
        "dúvida se faltou alguma informação da minha parte.\n\n"
        "Ficou alguma pergunta sobre quantidade mínima, prazo ou rótulo?",
        _botoes("Ficou uma dúvida", "Me chama depois", SAIDA_INTERESSE),
    ),
    _tpl(
        "joao_conversa_privatelabel_t2",
        "Oi {{1}}, é o João do Café Canastra de novo.\n\n"
        "Só para você ter em mente como funciona: o café é da nossa fazenda na Serra "
        "da Canastra, a torra é feita aqui e a embalagem sai com a sua marca, pronta "
        "para a sua prateleira.\n\n"
        "Você cuida da marca e da venda; a parte de café fica comigo. Faz sentido "
        "para o seu projeto?",
        _botoes("Faz sentido", "Tenho uma dúvida", SAIDA_INTERESSE),
    ),
    _tpl(
        "joao_conversa_privatelabel_t3",
        "Oi {{1}}, aqui é o João, do Café Canastra.\n\n"
        "A maioria das marcas que eu atendo começou com um lote pequeno, colocou o "
        "produto para rodar e só depois aumentou a tiragem.\n\n"
        "Se preferir, a gente pode começar assim, para você ver o produto pronto "
        "antes de assumir volume maior.",
        _botoes("Quero avaliar", "Tenho uma dúvida", SAIDA_INTERESSE),
    ),
    _tpl(
        "joao_conversa_privatelabel_t4",
        "Oi {{1}}, João aqui.\n\n"
        "Não quero te tomar tempo com conversa longa. Me diz só o tipo de embalagem "
        "que você tem em mente e quantos pacotes pretende fazer na primeira tiragem, "
        "que eu te devolvo a condição fechada.",
        _botoes("Vou te passar", "Prefiro falar depois", SAIDA_INTERESSE),
    ),
    _tpl(
        "joao_conversa_privatelabel_t5",
        "Oi {{1}}, aqui é o João, do Café Canastra.\n\n"
        "Faz um tempo que a gente não conversa e eu não sei se o projeto da sua marca "
        "ainda está de pé.\n\n"
        "Me dá um sinal para eu saber se sigo te procurando ou se deixo para mais "
        "para a frente?",
        _botoes("Ainda está de pé", "Deixa para depois", SAIDA_INTERESSE),
    ),
    _tpl(
        "joao_conversa_privatelabel_t6",
        "Oi {{1}}, é o João do Café Canastra.\n\n"
        "Entrou lote novo da safra aqui na fazenda e isso mexeu nas condições de "
        "primeira tiragem que a gente tinha conversado.\n\n"
        "Quer que eu te mande os números atualizados?",
        _botoes("Quero os números", "Agora não", SAIDA_INTERESSE),
    ),
    _tpl(
        "joao_conversa_privatelabel_t7",
        "Oi {{1}}, aqui é o João, do Café Canastra.\n\n"
        "Vou parar de te procurar por aqui para não virar incômodo.\n\n"
        "Se um dia você retomar o projeto da sua marca, é só me chamar neste mesmo "
        "número. Fico à disposição e sem pressa.",
        _botoes("Quero retomar agora", SAIDA_INTERESSE),
    ),
]

# ─────────────────────────────────────────────────────────────────────────────
# ESTEIRA "REPOSICAO" — card 45 dias em "Cliente Ativo", depois D+3, D+18, D+33.
# Publico e CLIENTE, nao prospect: o tom pressupoe relacao existente e o botao de
# saida e "Parar mensagens" (nao "Nao tenho interesse", que soa a ruptura com quem
# ja compra). Os dois sao reconhecidos por `is_optout_reply`.
# "Ainda tenho estoque" e literal da reuniao de 10/09 (Arthur, 41:40).
# ─────────────────────────────────────────────────────────────────────────────
REPOSICAO_ATACADO = [
    _tpl(
        "joao_reposicao_atacado_t1",
        "Oi {{1}}, aqui é o João, do Café Canastra.\n\n"
        "Faz um tempo desde a sua última compra e passei para saber como está o seu "
        "estoque de café por aí.\n\n"
        "Se já estiver apertado, eu te mando as condições desta semana.",
        _botoes("Preciso repor", "Ainda tenho estoque", SAIDA_PARAR),
    ),
    _tpl(
        "joao_reposicao_atacado_t2",
        "Oi {{1}}, é o João do Café Canastra.\n\n"
        "Minha mensagem anterior acabou ficando sem resposta e não quero te incomodar "
        "à toa.\n\n"
        "Me dá só um sinal para eu saber como seguir?",
        _botoes("Preciso repor", "Ainda tenho estoque", SAIDA_PARAR),
    ),
    _tpl(
        "joao_reposicao_atacado_t3",
        "Oi {{1}}, aqui é o João, do Café Canastra.\n\n"
        "Entrou lote novo da safra e as condições estão melhores do que na sua última "
        "compra.\n\n"
        "Quer que eu te mande a tabela atualizada para você comparar?",
        _botoes("Quero a tabela", "Ainda tenho estoque", SAIDA_PARAR),
    ),
    _tpl(
        "joao_reposicao_atacado_t4",
        "Oi {{1}}, é o João do Café Canastra.\n\n"
        "Vou parar de te chamar sobre reposição para não virar incômodo.\n\n"
        "Quando precisar de café, é só me mandar mensagem neste mesmo número que eu "
        "te atendo na hora.",
        _botoes("Quero repor agora", SAIDA_PARAR),
    ),
]

REPOSICAO_PRIVATE_LABEL = [
    _tpl(
        "joao_reposicao_privatelabel_t1",
        "Oi {{1}}, aqui é o João, do Café Canastra.\n\n"
        "Faz um tempo desde a sua última tiragem e passei para saber como está o "
        "estoque dos pacotes da sua marca.\n\n"
        "Se já estiver acabando, eu começo a preparar a próxima produção.",
        _botoes("Preciso repor", "Ainda tenho estoque", SAIDA_PARAR),
    ),
    _tpl(
        "joao_reposicao_privatelabel_t2",
        "Oi {{1}}, é o João do Café Canastra.\n\n"
        "Minha mensagem sobre a próxima tiragem da sua marca ficou sem resposta e não "
        "quero te incomodar à toa.\n\n"
        "Me dá só um sinal para eu saber se programo ou se deixo parado?",
        _botoes("Preciso repor", "Ainda tenho estoque", SAIDA_PARAR),
    ),
    _tpl(
        "joao_reposicao_privatelabel_t3",
        "Oi {{1}}, aqui é o João, do Café Canastra.\n\n"
        "Entrou lote novo da safra e dá para programar a sua próxima tiragem com uma "
        "condição melhor do que a anterior.\n\n"
        "Quer que eu te mande os números para comparar?",
        _botoes("Quero os números", "Ainda tenho estoque", SAIDA_PARAR),
    ),
    _tpl(
        "joao_reposicao_privatelabel_t4",
        "Oi {{1}}, é o João do Café Canastra.\n\n"
        "Vou parar de te chamar sobre reposição para não virar incômodo.\n\n"
        "Quando quiser programar a próxima tiragem da sua marca, é só me mandar "
        "mensagem neste mesmo número.",
        _botoes("Quero programar", SAIDA_PARAR),
    ),
]

TEMPLATES = (NOVO + EM_CONVERSA_ATACADO + EM_CONVERSA_PRIVATE_LABEL
             + REPOSICAO_ATACADO + REPOSICAO_PRIVATE_LABEL)

# ─────────────────────────────────────────────────────────────────────────────
# Auditoria — roda ANTES de qualquer chamada de rede.
# ─────────────────────────────────────────────────────────────────────────────
_ACENTO_PERDIDO = re.compile(r"[A-Za-z]\?[A-Za-z]|Ol\? ")


def _auditar(templates, vars_esperadas=frozenset({"1"})):
    """Devolve a lista de problemas. Vazia = seguro submeter.

    `vars_esperadas` existe porque `create_esteira_templates.py` (as 5 esteiras
    genericas) reusa esta auditoria com DUAS variaveis — la os nos ja gravam
    `{"1": "{{primeiro_nome}}", "2": "João"}` no `template_variables`, entao o corpo
    tem de pedir as duas. Aqui o padrao e uma so.
    """
    problemas = []
    vistos_nome, vistos_corpo = set(), {}
    for t in templates:
        nome = t["name"]
        corpo = next(c["text"] for c in t["components"] if c["type"] == "BODY")
        botoes = [b["text"] for c in t["components"] if c["type"] == "BUTTONS"
                  for b in c["buttons"]]

        if nome in vistos_nome:
            problemas.append(f"{nome}: nome duplicado")
        vistos_nome.add(nome)

        if not re.fullmatch(r"[a-z0-9_]+", nome):
            problemas.append(f"{nome}: nome invalido (so minuscula, digito e _)")

        # Regra 1 — encoding.
        if _ACENTO_PERDIDO.search(corpo) or any(_ACENTO_PERDIDO.search(b) for b in botoes):
            problemas.append(f"{nome}: ACENTO PERDIDO no texto de origem")
        if not any(ord(ch) > 127 for ch in corpo):
            problemas.append(f"{nome}: corpo sem nenhum acento — suspeito")

        # Regra 2 — botao de saida reconhecido pelo sistema.
        if not botoes:
            problemas.append(f"{nome}: sem botoes")
        else:
            ultimo = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", _sem_acento(botoes[-1]).lower())).strip()
            if ultimo not in SAIDAS_VALIDAS:
                problemas.append(
                    f"{nome}: botao de saida '{botoes[-1]}' NAO e reconhecido por "
                    f"is_optout_reply — seria um botao morto")

        # Regra 3 — uma variavel so.
        vars_ = set(re.findall(r"\{\{(\d+)\}\}", corpo))
        if vars_ != set(vars_esperadas):
            problemas.append(f"{nome}: variaveis {sorted(vars_)} — "
                             f"esperado {sorted(vars_esperadas)}")
        # O `example` tem de ter um valor por variavel ou a Meta recusa a submissao.
        exemplo = next((c.get("example", {}).get("body_text", [[]])[0]
                        for c in t["components"] if c["type"] == "BODY"), [])
        if len(exemplo) != len(vars_):
            problemas.append(f"{nome}: example com {len(exemplo)} valores para "
                             f"{len(vars_)} variaveis")

        # Limites da Meta.
        if len(corpo) > 1024:
            problemas.append(f"{nome}: corpo com {len(corpo)} chars (max 1024)")
        for b in botoes:
            if len(b) > 25:
                problemas.append(f"{nome}: botao '{b}' com {len(b)} chars (max 25)")
        rodape = [c["text"] for c in t["components"] if c["type"] == "FOOTER"]
        if rodape and len(rodape[0]) > 60:
            problemas.append(f"{nome}: rodape com {len(rodape[0])} chars (max 60)")

        # Texto repetido entre toques — o motor de cadencias nao tem dedup.
        chave = re.sub(r"\s+", " ", corpo).strip()
        if chave in vistos_corpo:
            problemas.append(f"{nome}: corpo identico ao de {vistos_corpo[chave]}")
        vistos_corpo[chave] = nome

    return problemas


def _sem_acento(txt):
    import unicodedata
    t = unicodedata.normalize("NFKD", txt)
    return "".join(c for c in t if not unicodedata.combining(c))


def submeter(tmpl):
    # ensure_ascii=True — a defesa da regra 1.
    payload = json.dumps(tmpl, ensure_ascii=True).encode("ascii")
    req = urllib.request.Request(
        f"https://graph.facebook.com/v21.0/{WABA_ID}/message_templates",
        data=payload, method="POST",
        headers={"Authorization": f"Bearer {TOKEN}",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return True, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return False, exc.read().decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    problemas = _auditar(TEMPLATES)
    print(f"{len(TEMPLATES)} templates definidos.")
    if problemas:
        print("\nAUDITORIA REPROVOU — nada foi submetido:")
        for p in problemas:
            print("  -", p)
        return 1
    print("Auditoria OK: acentos integros, botao de saida reconhecido, 1 variavel, "
          "sem texto repetido.\n")

    if "--submeter" not in sys.argv:
        for t in TEMPLATES:
            print(" ", t["name"])
        print("\n(dry-run) Use --submeter para enviar para a Meta.")
        return 0

    if not WABA_ID or not TOKEN:
        print("Defina META_WABA_ID e META_ACCESS_TOKEN no ambiente.")
        return 1

    ok = 0
    for t in TEMPLATES:
        sucesso, resposta = submeter(t)
        ok += bool(sucesso)
        print(f"{'OK  ' if sucesso else 'ERRO'} {t['name']}: {resposta}")
        time.sleep(1.2)
    print(f"\n{ok}/{len(TEMPLATES)} submetidos.")
    return 0 if ok == len(TEMPLATES) else 1


if __name__ == "__main__":
    raise SystemExit(main())
