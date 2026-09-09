"""
Cria 30 templates de utilidade (10 por publico) via Meta Graph API.
Idioma: en_US (aprovacao mais facil), texto em portugues.
Encoding: UTF-8 explicito para evitar corrupcao de caracteres.
"""

import os
import urllib.request
import json
import time

# 09/09/2026 — o token de acesso da Meta vivia AQUI em texto puro (~200 chars). O arquivo
# e untracked mas o .gitignore nao o cobre (`*.env*` nao casa com `.py`), entao um
# `git add -A` o publicaria no repositorio. Agora vem do ambiente, como em todo o resto
# do backend. Rode com as vars ja carregadas (backend/.env.local) ou exporte na sessao.
WABA_ID = os.environ.get("META_WABA_ID", "")
TOKEN = os.environ.get("META_ACCESS_TOKEN", "")
if not WABA_ID or not TOKEN:
    raise SystemExit(
        "META_WABA_ID e META_ACCESS_TOKEN precisam estar no ambiente. "
        "Ex.: export $(grep -E '^META_(WABA_ID|ACCESS_TOKEN)=' backend/.env.local | xargs)"
    )
CHANNEL_ID = "a3a607b1-6bff-4370-8609-b275eef270dd"
URL = f"https://graph.facebook.com/v21.0/{WABA_ID}/message_templates"

BUTTONS = [
    {"type": "QUICK_REPLY", "text": "Continuar atendimento"},
    {"type": "QUICK_REPLY", "text": "Tirar duvidas"},
    {"type": "QUICK_REPLY", "text": "Nao tenho interesse"},
]

def body(text, examples):
    return {
        "type": "BODY",
        "text": text,
        "example": {"body_text": [examples]},
    }

def buttons_component():
    return {"type": "BUTTONS", "buttons": BUTTONS}

TEMPLATES = [

    # ─── PUBLICO GERAL ────────────────────────────────────────────────────────
    # v1: ultra simples, 1 var — pt_BR
    {
        "name": "utilidade_geral_simples_v1",
        "language": "pt_BR",
        "components": [
            body(
                "Ola! Seu atendimento com o Cafe Canastra ainda esta em aberto. "
                "O {{1}} esta disponivel para continuarmos de onde paramos. "
                "Basta responder essa mensagem.",
                ["Joao"],
            ),
            buttons_component(),
        ],
    },
    # v2: simples, 2 vars — pt_BR
    {
        "name": "utilidade_geral_simples_v2",
        "language": "pt_BR",
        "components": [
            body(
                "Ola, {{1}}! Seu atendimento com o Cafe Canastra esta aguardando retorno. "
                "O {{2}} esta aqui para continuarmos de onde paramos. Basta responder.",
                ["Maria", "Joao"],
            ),
            buttons_component(),
        ],
    },
    # v3: com data, 3 vars — pt_BR
    {
        "name": "utilidade_geral_data_v1",
        "language": "pt_BR",
        "components": [
            body(
                "Ola, {{1}}! O {{2}} do Cafe Canastra notou que sua conversa ficou sem "
                "resposta desde {{3}}. Quando puder, responda essa mensagem para "
                "continuarmos seu atendimento.",
                ["Maria", "Joao", "21/05/2025"],
            ),
            buttons_component(),
        ],
    },
    # v4: com produto, 3 vars — pt_BR
    {
        "name": "utilidade_geral_produto_v1",
        "language": "pt_BR",
        "components": [
            body(
                "Ola, {{1}}! Seu pedido de {{2}} no Cafe Canastra esta em aberto. "
                "O {{3}} esta aguardando seu retorno para dar andamento ao atendimento.",
                ["Carlos", "cafe especial", "Joao"],
            ),
            buttons_component(),
        ],
    },
    # v5: confirmacao, 3 vars — en_US (teste)
    {
        "name": "utilidade_geral_confirmacao_v1",
        "language": "en_US",
        "components": [
            body(
                "Ola, {{1}}! O Cafe Canastra esta aguardando sua confirmacao sobre "
                "{{2}} desde {{3}}. Responda essa mensagem para finalizarmos seu atendimento.",
                ["Ana", "seu pedido de cafe", "20/05/2025"],
            ),
            buttons_component(),
        ],
    },
    # v6: com prazo, 3 vars — en_US (teste)
    {
        "name": "utilidade_geral_prazo_v1",
        "language": "en_US",
        "components": [
            body(
                "Ola, {{1}}! O {{2}} do Cafe Canastra ainda pode dar andamento ao seu "
                "atendimento ate {{3}}. Para continuarmos, basta responder essa mensagem.",
                ["Pedro", "Joao", "30/05/2025"],
            ),
            buttons_component(),
        ],
    },
    # v7: resumo, 4 vars — pt_BR
    {
        "name": "utilidade_geral_resumo_v1",
        "language": "pt_BR",
        "components": [
            body(
                "Ola, {{1}}! Aqui e o {{2}} do Cafe Canastra. Seu atendimento sobre "
                "{{3}} ficou em aberto desde {{4}}. Responda essa mensagem para que "
                "possamos continuar.",
                ["Maria", "Joao", "cafe especial moido", "19/05/2025"],
            ),
            buttons_component(),
        ],
    },
    # v8: resumo variante, 4 vars — en_US (teste)
    {
        "name": "utilidade_geral_resumo_v2",
        "language": "en_US",
        "components": [
            body(
                "Ola, {{1}}! O {{2}} do Cafe Canastra esta aguardando seu retorno desde "
                "{{3}} para finalizar seu pedido de {{4}}. Quando puder, responda essa mensagem.",
                ["Carlos", "Joao", "22/05/2025", "cafe 250g"],
            ),
            buttons_component(),
        ],
    },
    # v9: completo com prazo, 5 vars — en_US (teste)
    {
        "name": "utilidade_geral_completo_v1",
        "language": "en_US",
        "components": [
            body(
                "Ola, {{1}}! Sou o {{2}} do Cafe Canastra. Seu atendimento sobre {{3}} "
                "ficou em aberto desde {{4}}. Estamos disponiveis ate {{5}} para dar "
                "continuidade ao seu pedido. Responda essa mensagem para continuarmos.",
                ["Maria", "Joao", "cafe especial", "20/05/2025", "30/05/2025"],
            ),
            buttons_component(),
        ],
    },
    # v10: completo variante, 5 vars — en_US (teste)
    {
        "name": "utilidade_geral_completo_v2",
        "language": "en_US",
        "components": [
            body(
                "Ola, {{1}}! O {{2}} do Cafe Canastra esta entrando em contato porque "
                "sua solicitacao de {{3}}, feita em {{4}}, ainda aguarda resposta. "
                "Seu atendimento tem prioridade e podemos finalizar ate {{5}}. "
                "Responda essa mensagem para continuarmos.",
                ["Maria", "Joao", "cafe especial", "20/05/2025", "30/05/2025"],
            ),
            buttons_component(),
        ],
    },

    # ─── CAFETERIAS ──────────────────────────────────────────────────────────
    # c1: ultra simples, 1 var — pt_BR
    {
        "name": "utilidade_cafeteria_simples_v1",
        "language": "pt_BR",
        "components": [
            body(
                "Ola! Aqui e o Cafe Canastra. O atendimento da cafeteria ainda esta "
                "em aberto com {{1}}. Responda essa mensagem para continuarmos o pedido.",
                ["Joao"],
            ),
            buttons_component(),
        ],
    },
    # c2: simples, 2 vars — pt_BR
    {
        "name": "utilidade_cafeteria_simples_v2",
        "language": "pt_BR",
        "components": [
            body(
                "Ola, {{1}}! O Cafe Canastra esta aguardando o retorno da cafeteria. "
                "O {{2}} esta disponivel para dar continuidade ao pedido. "
                "Responda essa mensagem.",
                ["Carlos", "Joao"],
            ),
            buttons_component(),
        ],
    },
    # c3: nome cafeteria, 3 vars — pt_BR
    {
        "name": "utilidade_cafeteria_nome_v1",
        "language": "pt_BR",
        "components": [
            body(
                "Ola, {{1}}! O {{2}} do Cafe Canastra esta aguardando o retorno da "
                "{{3}} para dar andamento ao pedido em aberto. Basta responder essa mensagem.",
                ["Carlos", "Joao", "Cafeteria Grao Nobre"],
            ),
            buttons_component(),
        ],
    },
    # c4: com data, 3 vars — en_US (teste)
    {
        "name": "utilidade_cafeteria_data_v1",
        "language": "en_US",
        "components": [
            body(
                "Ola, {{1}}! A conversa entre o Cafe Canastra e a {{2}} ficou pausada "
                "em {{3}}. O atendimento ainda esta aberto. Responda para continuarmos.",
                ["Carlos", "Cafeteria Grao Nobre", "20/05/2025"],
            ),
            buttons_component(),
        ],
    },
    # c5: com blend, 3 vars — pt_BR
    {
        "name": "utilidade_cafeteria_produto_v1",
        "language": "pt_BR",
        "components": [
            body(
                "Ola, {{1}}! O pedido de {{2}} da {{3}} no Cafe Canastra ainda esta "
                "aguardando confirmacao. Responda essa mensagem para finalizarmos o atendimento.",
                ["Carlos", "Blend Cerrado Mineiro", "Cafeteria Grao Nobre"],
            ),
            buttons_component(),
        ],
    },
    # c6: com prazo, 3 vars — en_US (teste)
    {
        "name": "utilidade_cafeteria_prazo_v1",
        "language": "en_US",
        "components": [
            body(
                "Ola, {{1}}! O Cafe Canastra pode finalizar o pedido da {{2}} ate "
                "{{3}}. Para continuarmos o atendimento, basta responder essa mensagem.",
                ["Carlos", "Cafeteria Grao Nobre", "30/05/2025"],
            ),
            buttons_component(),
        ],
    },
    # c7: resumo, 4 vars — pt_BR
    {
        "name": "utilidade_cafeteria_resumo_v1",
        "language": "pt_BR",
        "components": [
            body(
                "Ola, {{1}}! Aqui e o {{2}} do Cafe Canastra. O atendimento da {{3}} "
                "sobre {{4}} esta em aberto. Responda essa mensagem para darmos continuidade.",
                ["Carlos", "Joao", "Cafeteria Grao Nobre", "Blend Cerrado Mineiro"],
            ),
            buttons_component(),
        ],
    },
    # c8: resumo variante, 4 vars — en_US (teste)
    {
        "name": "utilidade_cafeteria_resumo_v2",
        "language": "en_US",
        "components": [
            body(
                "Ola, {{1}}! O {{2}} do Cafe Canastra esta aguardando o retorno da "
                "{{3}} desde {{4}} para fechar o pedido. Quando puder, responda essa mensagem.",
                ["Carlos", "Joao", "Cafeteria Grao Nobre", "19/05/2025"],
            ),
            buttons_component(),
        ],
    },
    # c9: completo v1, 5 vars — en_US (teste)
    {
        "name": "utilidade_cafeteria_completo_v1",
        "language": "en_US",
        "components": [
            body(
                "Ola, {{1}}! Sou o {{2}} do Cafe Canastra. O pedido de {{3}} da {{4}} "
                "ficou em aberto desde {{5}} e precisa de confirmacao. Responda essa "
                "mensagem para que possamos dar andamento ao atendimento.",
                ["Carlos", "Joao", "Blend Cerrado Mineiro", "Cafeteria Grao Nobre", "19/05/2025"],
            ),
            buttons_component(),
        ],
    },
    # c10: completo v2, 5 vars — en_US (teste)
    {
        "name": "utilidade_cafeteria_completo_v2",
        "language": "en_US",
        "components": [
            body(
                "Ola, {{1}}! O {{2}} do Cafe Canastra esta entrando em contato porque "
                "o atendimento da {{3}} referente a {{4}} esta sem resposta desde {{5}}. "
                "Para darmos continuidade ao pedido, basta responder essa mensagem.",
                ["Carlos", "Joao", "Cafeteria Grao Nobre", "Blend Cerrado Mineiro", "19/05/2025"],
            ),
            buttons_component(),
        ],
    },

    # ─── EMPORIOS ────────────────────────────────────────────────────────────
    # e1: ultra simples, 1 var — pt_BR
    {
        "name": "utilidade_emporio_simples_v1",
        "language": "pt_BR",
        "components": [
            body(
                "Ola! Aqui e o Cafe Canastra. Seu atendimento ainda esta em aberto "
                "com {{1}}. Responda essa mensagem para continuarmos o seu pedido.",
                ["Joao"],
            ),
            buttons_component(),
        ],
    },
    # e2: simples, 2 vars — pt_BR
    {
        "name": "utilidade_emporio_simples_v2",
        "language": "pt_BR",
        "components": [
            body(
                "Ola, {{1}}! O Cafe Canastra esta aguardando o retorno do emporio. "
                "O {{2}} esta disponivel para dar continuidade ao atendimento. "
                "Responda essa mensagem.",
                ["Ana", "Joao"],
            ),
            buttons_component(),
        ],
    },
    # e3: nome emporio, 3 vars — pt_BR
    {
        "name": "utilidade_emporio_nome_v1",
        "language": "pt_BR",
        "components": [
            body(
                "Ola, {{1}}! O {{2}} do Cafe Canastra esta aguardando retorno do {{3}} "
                "para dar andamento ao pedido em aberto. Basta responder essa mensagem.",
                ["Ana", "Joao", "Emporio Sabor da Serra"],
            ),
            buttons_component(),
        ],
    },
    # e4: com data, 3 vars — en_US (teste)
    {
        "name": "utilidade_emporio_data_v1",
        "language": "en_US",
        "components": [
            body(
                "Ola, {{1}}! A conversa entre o Cafe Canastra e o {{2}} ficou pausada "
                "em {{3}}. O atendimento ainda esta aberto. Responda para continuarmos.",
                ["Ana", "Emporio Sabor da Serra", "18/05/2025"],
            ),
            buttons_component(),
        ],
    },
    # e5: com linha de produto, 3 vars — pt_BR
    {
        "name": "utilidade_emporio_produto_v1",
        "language": "pt_BR",
        "components": [
            body(
                "Ola, {{1}}! O pedido de {{2}} do {{3}} no Cafe Canastra ainda esta "
                "aguardando confirmacao. Responda essa mensagem para finalizarmos o atendimento.",
                ["Ana", "linha de cafes especiais 250g", "Emporio Sabor da Serra"],
            ),
            buttons_component(),
        ],
    },
    # e6: com prazo, 3 vars — en_US (teste)
    {
        "name": "utilidade_emporio_prazo_v1",
        "language": "en_US",
        "components": [
            body(
                "Ola, {{1}}! O Cafe Canastra pode finalizar o pedido do {{2}} ate "
                "{{3}}. Para continuarmos o atendimento, basta responder essa mensagem.",
                ["Ana", "Emporio Sabor da Serra", "30/05/2025"],
            ),
            buttons_component(),
        ],
    },
    # e7: resumo, 4 vars — pt_BR
    {
        "name": "utilidade_emporio_resumo_v1",
        "language": "pt_BR",
        "components": [
            body(
                "Ola, {{1}}! Aqui e o {{2}} do Cafe Canastra. O atendimento do {{3}} "
                "sobre {{4}} esta em aberto. Responda essa mensagem para darmos continuidade.",
                ["Ana", "Joao", "Emporio Sabor da Serra", "cafes especiais 250g"],
            ),
            buttons_component(),
        ],
    },
    # e8: resumo variante, 4 vars — en_US (teste)
    {
        "name": "utilidade_emporio_resumo_v2",
        "language": "en_US",
        "components": [
            body(
                "Ola, {{1}}! O {{2}} do Cafe Canastra esta aguardando o retorno do "
                "{{3}} desde {{4}} para fechar o pedido. Quando puder, responda essa mensagem.",
                ["Ana", "Joao", "Emporio Sabor da Serra", "18/05/2025"],
            ),
            buttons_component(),
        ],
    },
    # e9: completo v1, 5 vars — en_US (teste)
    {
        "name": "utilidade_emporio_completo_v1",
        "language": "en_US",
        "components": [
            body(
                "Ola, {{1}}! Sou o {{2}} do Cafe Canastra. O pedido de {{3}} do {{4}} "
                "ficou em aberto desde {{5}} e precisa de confirmacao. Responda essa "
                "mensagem para que possamos dar andamento ao atendimento.",
                ["Ana", "Joao", "cafes especiais 250g", "Emporio Sabor da Serra", "18/05/2025"],
            ),
            buttons_component(),
        ],
    },
    # e10: completo v2, 5 vars — en_US (teste)
    {
        "name": "utilidade_emporio_completo_v2",
        "language": "en_US",
        "components": [
            body(
                "Ola, {{1}}! O {{2}} do Cafe Canastra esta entrando em contato porque "
                "o atendimento do {{3}} referente a {{4}} esta sem resposta desde {{5}}. "
                "Para darmos continuidade ao pedido, basta responder essa mensagem.",
                ["Ana", "Joao", "Emporio Sabor da Serra", "linha de cafes especiais", "18/05/2025"],
            ),
            buttons_component(),
        ],
    },
]

def create_template(tmpl):
    payload = {
        "name": tmpl["name"],
        "language": tmpl.get("language", "pt_BR"),
        "category": "UTILITY",
        "components": tmpl["components"],
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        URL,
        data=data,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {TOKEN}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return True, result
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8")
        return False, err
    except Exception as ex:
        return False, str(ex)


results = []
print(f"Criando {len(TEMPLATES)} templates...\n")

for i, tmpl in enumerate(TEMPLATES, 1):
    ok, resp = create_template(tmpl)
    label = "OK " if ok else "ERR"
    if ok:
        meta_id = resp.get("id")
        status = resp.get("status")
        category = resp.get("category")
        print(f"[{i:02d}/{len(TEMPLATES)}] {label}  {tmpl['name']:<45}  id={meta_id}  {status}/{category}")
        results.append({
            "name": tmpl["name"],
            "ok": True,
            "meta_id": meta_id,
            "status": status,
            "category": category,
            "components": tmpl["components"],
        })
    else:
        print(f"[{i:02d}/{len(TEMPLATES)}] {label}  {tmpl['name']:<45}  {str(resp)[:120]}")
        results.append({"name": tmpl["name"], "ok": False, "error": resp})
    time.sleep(1.2)

# Build SQL for successful templates
ok_results = [r for r in results if r["ok"]]
print(f"\n\n--- RESULTADO ---")
print(f"Criados com sucesso: {len(ok_results)}/{len(TEMPLATES)}")
print(f"Falhas: {len(TEMPLATES) - len(ok_results)}")

if ok_results:
    print("\n-- SQL para inserir no banco --")
    rows = []
    for r in ok_results:
        comps = json.dumps(r["components"], ensure_ascii=False).replace("'", "''")
        rows.append(
            f"('{CHANNEL_ID}', '{r['name']}', 'en_US', 'UTILITY', '{r['category']}', "
            f"'{comps}'::jsonb, '{r['meta_id']}', 'pending')"
        )
    sql = (
        "INSERT INTO message_templates "
        "(channel_id, name, language, requested_category, category, components, meta_template_id, status) VALUES\n"
        + ",\n".join(rows)
        + "\nRETURNING id, name, status;"
    )
    # Print to file for inspection
    with open("scripts/insert_templates.sql", "w", encoding="utf-8") as f:
        f.write(sql)
    print("SQL salvo em scripts/insert_templates.sql")
