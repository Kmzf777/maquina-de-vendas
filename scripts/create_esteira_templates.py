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

ACENTUACAO: os corpos e os botoes vao em portugues correto, com acento — sao
mensagens para o cliente de uma marca de cafe especial, saindo do numero PESSOAL do
vendedor, e "Aqui e o Joao" le como portugues quebrado.

O QUE MUDOU EM 13/09/2026: a versao anterior deste arquivo submetia com
`ensure_ascii=False` e defendia a escolha ("nada aqui exige ASCII"). A evidencia
derrubou o argumento: tres templates do lote de 25/05/2026 chegaram a Meta com os
acentos ja virados em '?' e a corrupcao ficou GRAVADA — `check_estoque_reposicao`
vivia em producao como "Ol? {{1}}, aqui ? o Jo?o da Caf? Canastra ?", com zero
caracteres nao-ASCII no corpo. Agora o payload sai com `ensure_ascii=True`: o JSON
viaja em ASCII puro com cada acento como escape de 6 caracteres, o cliente recebe o
acento correto do mesmo jeito, e nao existe mais um caminho no qual a corrupcao possa
acontecer.

AUDITORIA: a checagem vem de `create_templates_esteiras_joao.py` (mesma pasta) para os
dois scripts nao divergirem. Ela recusa submeter corpo com acento perdido, botao de
saida que o sistema nao reconhece, `example` com numero errado de valores e texto
repetido entre templates.

"""
import json
import os
import sys
import time
import urllib.request

WABA_ID = os.environ.get("META_WABA_ID")
TOKEN = os.environ.get("META_ACCESS_TOKEN")

# A checagem de credencial e PREGUICOSA de proposito — so barra quem vai submeter de
# verdade. No nivel do modulo ela derrubava o import inteiro com `sys.exit`, o que
# impedia os testes de auditar estes textos sem ter um token da Meta a mao. Auditar
# nao toca a rede; so `submeter` toca.
def _exigir_credenciais():
    if not WABA_ID or not TOKEN:
        raise SystemExit("Defina META_WABA_ID e META_ACCESS_TOKEN no ambiente.")


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
    }, ensure_ascii=True).encode("ascii")
    req = urllib.request.Request(
        URL, data=payload, method="POST",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return True, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return False, exc.read().decode("utf-8")
    except Exception as exc:
        return False, str(exc)


def _para_auditar():
    """Forma que `_auditar` entende — ela le `category` junto com os components."""
    return [{**t, "category": "UTILITY"} for t in TEMPLATES]


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")

    # Auditoria compartilhada com create_templates_esteiras_joao.py. Duas variaveis
    # aqui ({{1}} nome, {{2}} vendedor) porque e o que os nos destas 5 campanhas ja
    # gravam em `template_variables` — verificado em producao em 13/09/2026.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from create_templates_esteiras_joao import _auditar

    problemas = _auditar(_para_auditar(), vars_esperadas={"1", "2"})
    if problemas:
        print("AUDITORIA REPROVOU — nada foi submetido:")
        for p in problemas:
            print("  -", p)
        raise SystemExit(1)
    print(f"Auditoria OK nos {len(TEMPLATES)} templates.\n")

    if "--submeter" not in sys.argv:
        for t in TEMPLATES:
            print(" ", t["name"])
        print("\n(dry-run) Use --submeter para enviar para a Meta.")
        raise SystemExit(0)

    _exigir_credenciais()
    for tmpl in TEMPLATES:
        ok, resposta = submeter(tmpl)
        print(f"{'OK  ' if ok else 'ERRO'} {tmpl['name']}: {resposta}")
        time.sleep(1.2)
