"""Submete na Meta os 5 templates das esteiras do vendedor.

Spec: docs/superpowers/specs/2026-09-04-esteiras-vendedor-design.md §7

Uso:
    META_WABA_ID=... META_ACCESS_TOKEN=... python scripts/create_esteira_templates.py

Diferente de scripts/create_utility_templates.py, este NAO tem credencial no
arquivo — token em codigo versionado vaza no historico do git para sempre.

LOCALE: submetemos em pt_BR, mas o que vale e o idioma que a Meta APROVAR. O
template automacao_valeria_to_joao foi aprovado so em `en` (corpo em portugues) e o
default pt_BR causava 404 #132001 com o job cancelado sem entregar. Depois da
aprovacao, confira em message_templates e ajuste `template_language` na config do
no de envio.

ACENTUACAO: os corpos e os botoes vao em portugues correto, com acento. Isto e
deliberado e nada aqui exige ASCII — o payload sai com `ensure_ascii=False` e o
Content-Type declara `charset=utf-8`. Sao mensagens para o cliente de uma marca de
cafe especial, saindo do numero PESSOAL do vendedor: "Aqui e o Joao" le como
portugues quebrado. E, uma vez submetido e aprovado, mudar o texto exige criar uma
nova versao do template na Meta — nao da para corrigir depois sem refazer o ciclo.
(Os comentarios e docstrings deste arquivo seguem em ASCII, como o resto do repo; a
regra vale para o que o CLIENTE le.)
"""
import json
import os
import sys
import time
import urllib.request

WABA_ID = os.environ.get("META_WABA_ID")
TOKEN = os.environ.get("META_ACCESS_TOKEN")
if not WABA_ID or not TOKEN:
    sys.exit("Defina META_WABA_ID e META_ACCESS_TOKEN no ambiente.")

URL = f"https://graph.facebook.com/v21.0/{WABA_ID}/message_templates"

# O terceiro botao ("Nao tenho interesse") ja alimenta a blacklist no fluxo atual —
# e a saida digna que protege o rating do numero de bloqueio em massa. O acento nao
# quebra esse caminho: `agent/tools.py::_looks_like_soft_rejection` normaliza em NFD e
# descarta os diacriticos antes de comparar.
BUTTONS = [
    {"type": "QUICK_REPLY", "text": "Continuar atendimento"},
    {"type": "QUICK_REPLY", "text": "Tirar dúvidas"},
    {"type": "QUICK_REPLY", "text": "Não tenho interesse"},
]


def body(text, examples):
    return {"type": "BODY", "text": text, "example": {"body_text": [examples]}}


TEMPLATES = [
    {
        "name": "esteira_novo_sem_resposta_v1",
        "language": "pt_BR",
        "components": [
            body(
                "Olá, {{1}}! Aqui é o {{2}}, do Café Canastra. Vi que sua mensagem ficou "
                "sem retorno e a responsabilidade é nossa. Sigo à disposição para te "
                "passar valores e condições. Posso continuar por aqui?",
                ["Marcella", "João"],
            ),
            {"type": "BUTTONS", "buttons": BUTTONS},
        ],
    },
    {
        "name": "esteira_novo_reengajamento_v1",
        "language": "pt_BR",
        "components": [
            body(
                "Olá, {{1}}! Aqui é o {{2}}, do Café Canastra. Nosso atendimento ficou "
                "em aberto e queria saber se você ainda tem interesse. Basta responder "
                "esta mensagem que sigo de onde paramos.",
                ["Marcella", "João"],
            ),
            {"type": "BUTTONS", "buttons": BUTTONS},
        ],
    },
    {
        "name": "esteira_reposicao_v1",
        "language": "pt_BR",
        "components": [
            body(
                "Olá, {{1}}! Aqui é o {{2}}, do Café Canastra. Faz um tempo desde o "
                "nosso último contato e queria saber como está seu estoque. Se quiser, "
                "te mando as condições atuais.",
                ["Marcella", "João"],
            ),
            {"type": "BUTTONS", "buttons": BUTTONS},
        ],
    },
    {
        "name": "esteira_proposta_d3_v1",
        "language": "pt_BR",
        "components": [
            body(
                "Olá, {{1}}! Aqui é o {{2}}, do Café Canastra. Passando para saber se "
                "você conseguiu ver a proposta que te enviei. Qualquer dúvida sobre "
                "valores, prazo ou personalização, é só responder aqui.",
                ["Marcella", "João"],
            ),
            {"type": "BUTTONS", "buttons": BUTTONS},
        ],
    },
    {
        "name": "esteira_proposta_d8_v1",
        "language": "pt_BR",
        "components": [
            body(
                "Olá, {{1}}! Aqui é o {{2}}, do Café Canastra. Sua proposta continua "
                "valendo e não quero que você perca o prazo. Me diz se faz sentido "
                "seguir ou se prefere que eu ajuste alguma coisa.",
                ["Marcella", "João"],
            ),
            {"type": "BUTTONS", "buttons": BUTTONS},
        ],
    },
]


def submeter(tmpl):
    payload = json.dumps({
        "name": tmpl["name"],
        "language": tmpl["language"],
        "category": "UTILITY",
        "components": tmpl["components"],
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        URL, data=payload, method="POST",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return True, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return False, exc.read().decode("utf-8")
    except Exception as exc:
        return False, str(exc)


if __name__ == "__main__":
    for tmpl in TEMPLATES:
        ok, resposta = submeter(tmpl)
        print(f"{'OK ' if ok else 'ERRO'} {tmpl['name']}: {resposta}")
        time.sleep(1.2)
