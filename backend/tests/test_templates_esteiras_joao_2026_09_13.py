"""Contrato entre o TEXTO dos 24 templates e o que o sistema faz com a resposta.

Um template e um objeto que vive na Meta, fora do repo — nada aqui impede que alguem
escreva um corpo bonito com um botao que nao faz nada. Foi exatamente o que estava em
producao ate 13/09/2026: os tres templates de reposicao/cotacao ofereciam
"Nao atendo mais", "Tirar dos contatos" e "Nao tenho mais interesse" como saida, e
NENHUM dos tres e reconhecido por `campaigns/worker.py::is_optout_reply`, que compara
por IGUALDADE normalizada contra um frozenset de duas frases. O lead apertava o botao
pedindo para sair, o sistema cancelava o enrollment e mais nada: sem `leads.opt_out`,
sem funil Blacklist, sem cancelar follow-up — e dias depois ele era reinscrito.

Note o "mais" em "Nao tenho mais interesse": uma palavra a mais no rotulo e a diferenca
entre honrar o pedido do lead e ignora-lo. Nenhum teste pegava isso porque o rotulo
vivia so no script de submissao e o matcher so no worker; os dois nunca se encontravam.
Estes testes sao esse encontro.
"""
import importlib.util
import pathlib
import re
import unicodedata

from app.campaigns.worker import is_optout_reply

# Carregado por CAMINHO, nao por `from scripts import ...`: existem dois diretorios
# `scripts/` no repo e o nome do pacote resolve para `backend/scripts/` (onde vive
# `apply_migrations`). O script dos templates fica na raiz, ao lado do irmao
# `create_esteira_templates.py`.
_SCRIPTS = pathlib.Path(__file__).resolve().parents[2] / "scripts"


def _carregar(nome):
    spec = importlib.util.spec_from_file_location(nome, _SCRIPTS / f"{nome}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tpls = _carregar("create_templates_esteiras_joao")
# As 5 esteiras GENERICAS (`app/campaigns/esteiras.py`), que valem para qualquer
# instalacao e nao so para o Joao. Ficaram 9 dias apontando para templates que nunca
# existiram na Meta — o script estava escrito mas nunca tinha sido executado —, entao
# qualquer envio delas teria falhado. Submetidos em 13/09/2026.
gen = _carregar("create_esteira_templates")


def _corpo(t):
    return next(c["text"] for c in t["components"] if c["type"] == "BODY")


def _botoes(t):
    return [b["text"] for c in t["components"] if c["type"] == "BUTTONS"
            for b in c["buttons"]]


def test_sao_24_templates_um_por_no_de_envio():
    assert len(tpls.TEMPLATES) == 24


def test_auditoria_do_proprio_script_passa():
    """O script recusa submeter o que nao passa — aqui a recusa vira teste."""
    assert tpls._auditar(tpls.TEMPLATES) == []


def test_todo_template_oferece_uma_saida_QUE_O_SISTEMA_RECONHECE():
    """O invariante central: o botao de saida tem de casar com `is_optout_reply`.

    Sem isto o botao e decorativo — e um botao de saida decorativo e pior que nenhum,
    porque o proximo passo do lead que pediu para sair e o "Bloquear" do WhatsApp.
    """
    for t in tpls.TEMPLATES:
        vivos = [b for b in _botoes(t) if is_optout_reply(b)]
        assert vivos, (
            f"{t['name']}: nenhum dos botoes {_botoes(t)} e reconhecido por "
            f"is_optout_reply — o lead nao consegue sair")


def test_a_saida_e_o_ultimo_botao():
    """Convencao do WhatsApp: a saida fica por ultimo, longe do polegar."""
    for t in tpls.TEMPLATES:
        assert is_optout_reply(_botoes(t)[-1]), f"{t['name']}: saida nao e o ultimo botao"


def test_nenhum_botao_de_acao_e_confundido_com_saida():
    """O inverso: 'Preciso repor' nao pode blacklistar quem quer comprar.

    `is_optout_reply` compara por igualdade justamente para isso — substring faria
    "nao tenho interesse em capsulas, so em graos" virar blacklist permanente.
    """
    for t in tpls.TEMPLATES:
        for b in _botoes(t)[:-1]:
            assert not is_optout_reply(b), f"{t['name']}: botao de acao '{b}' vira opt-out"


def test_acentuacao_integra_em_todo_corpo_e_botao():
    """A falha de 25/05/2026 gravou '?' no lugar dos acentos, permanentemente."""
    perdido = re.compile(r"[A-Za-z]\?[A-Za-z]|Ol\? ")
    for t in tpls.TEMPLATES:
        assert not perdido.search(_corpo(t)), f"{t['name']}: acento perdido no corpo"
        for b in _botoes(t):
            assert not perdido.search(b), f"{t['name']}: acento perdido no botao '{b}'"
        assert any(ord(c) > 127 for c in _corpo(t)), (
            f"{t['name']}: corpo sem nenhum caractere acentuado — sinal de corrupcao")


def test_payload_sai_em_ascii_puro():
    """A defesa contra o bug de encoding: nenhum byte >127 chega na rede.

    O corpo TEM acento (teste acima); o que garante a viagem intacta e o
    `ensure_ascii=True` da serializacao, que transforma cada acento num escape.
    """
    import json
    bruto = json.dumps(tpls.TEMPLATES, ensure_ascii=True)
    assert bruto.encode("ascii")  # nao levanta
    assert "\\u00e3" in bruto     # 'a' com til sobreviveu como escape


def test_uma_variavel_so_e_o_example_bate():
    for t in tpls.TEMPLATES:
        corpo = _corpo(t)
        assert set(re.findall(r"\{\{(\d+)\}\}", corpo)) == {"1"}, t["name"]
        exemplo = next(c["example"]["body_text"][0]
                       for c in t["components"] if c["type"] == "BODY")
        assert len(exemplo) == 1, f"{t['name']}: example com {len(exemplo)} valores"


def test_limites_da_meta():
    for t in tpls.TEMPLATES:
        assert len(_corpo(t)) <= 1024, f"{t['name']}: corpo longo demais"
        for b in _botoes(t):
            assert len(b) <= 25, f"{t['name']}: botao '{b}' > 25 chars"
        for c in t["components"]:
            if c["type"] == "FOOTER":
                assert len(c["text"]) <= 60


def test_todos_marketing_para_o_optout_ser_consistente():
    """Categoria unica por esteira.

    O opt-out de marketing do WhatsApp e POR CATEGORIA: uma esteira com categorias
    misturadas entregaria alguns toques e silenciaria outros para o mesmo lead.
    """
    assert {t["category"] for t in tpls.TEMPLATES} == {"MARKETING"}


# Os 24 nomes APROVADOS na Meta em 13/09/2026. Ficam fixados aqui, como dado
# literal, porque um template aprovado e um objeto que vive FORA do repo: renomear
# um no script nao quebra nada na suite, mas faz o envio real morrer com o erro
# #132001 ("template name does not exist") no primeiro disparo em producao.
#
# Ate 18/09/2026 este invariante era checado por cruzamento com `TEMPLATE_POR_TOQUE`
# (o mapa toque->template que vivia no seed das esteiras-campanha do Joao). O seed foi
# apagado quando as cadencias do Joao deixaram de ser campanhas do builder e viraram
# `job_type` em `follow_up_jobs` — ver
# docs/superpowers/specs/2026-09-18-motor-followup-joao-design.md. O mapa renasce em
# `follow_up/cadence_joao.py`, e o cruzamento com ELE e teste da task que o criar; o
# que nao podia acontecer e o intervalo entre as duas coisas deixar os 24 nomes sem
# guarda nenhuma.
NOMES_APROVADOS_NA_META = {
    "joao_novo_atacado_t1",
    "joao_novo_privatelabel_t1",
    *(f"joao_conversa_atacado_t{n}" for n in range(1, 8)),
    *(f"joao_conversa_privatelabel_t{n}" for n in range(1, 8)),
    *(f"joao_reposicao_atacado_t{n}" for n in range(1, 5)),
    *(f"joao_reposicao_privatelabel_t{n}" for n in range(1, 5)),
}


def test_os_nomes_do_script_sao_os_24_aprovados_na_meta():
    """Renomear um template no script nao renomeia o objeto aprovado na Meta.

    O script e a nossa unica copia do que foi submetido; se ele passar a dizer outro
    nome, quem quer que monte o envio (hoje o motor de follow-up do Joao) pedira a
    Meta um template que nao existe, e o erro so aparece no primeiro disparo real.
    """
    no_script = {t["name"] for t in tpls.TEMPLATES}
    assert no_script == NOMES_APROVADOS_NA_META, (
        f"so no script: {sorted(no_script - NOMES_APROVADOS_NA_META)}; "
        f"so entre os aprovados: {sorted(NOMES_APROVADOS_NA_META - no_script)}")


def test_rotulos_que_parecem_saida_mas_nao_sao():
    """Documenta a armadilha que derrubou os tres templates antigos."""
    def norm(s):
        t = unicodedata.normalize("NFKD", s.lower())
        return "".join(c for c in t if not unicodedata.combining(c))

    for morto in ("Nao atendo mais", "Tirar dos contatos", "Nao tenho mais interesse",
                  "Sair da lista", "Pode parar", "Nao me chame mais"):
        assert not is_optout_reply(morto), (
            f"'{morto}' passou a ser reconhecido — atualize os templates para usa-lo")
    for vivo in ("Nao tenho interesse", "Não tenho interesse", "PARAR MENSAGENS"):
        assert is_optout_reply(vivo), f"'{vivo}' deixou de ser reconhecido"
        assert norm(vivo) in {"nao tenho interesse", "parar mensagens"}


# ── As 5 esteiras genericas (`app/campaigns/esteiras.py`) ────────────────────────
#
# Mesmo contrato dos 24 do Joao, com UMA diferenca: os nos delas gravam DUAS variaveis
# (`{"1": "{{primeiro_nome}}", "2": "João"}` — verificado em producao em 13/09/2026),
# entao os corpos tem de pedir {{1}} e {{2}}. A auditoria e a mesma funcao.


def test_os_5_genericos_passam_na_auditoria_com_duas_variaveis():
    assert tpls._auditar(gen._para_auditar(), vars_esperadas={"1", "2"}) == []


def test_os_5_genericos_oferecem_saida_que_o_sistema_reconhece():
    for t in gen.TEMPLATES:
        assert is_optout_reply(_botoes(t)[-1]), (
            f"{t['name']}: saida '{_botoes(t)[-1]}' nao e reconhecida por is_optout_reply")


def test_os_5_genericos_cobrem_exatamente_o_seed_generico():
    """Se o seed e o script divergirem, o envio falha em producao, nao aqui.

    Foi o estado real entre 04/09 e 13/09/2026: o seed referenciava cinco nomes
    `esteira_*` e nenhum existia na WABA.
    """
    from app.campaigns import esteiras
    no_seed = {no["config"]["template_name"]
               for e in esteiras.ESTEIRAS for no in e["nodes"]
               if no["type"] == "send" and no["config"].get("template_name")}
    no_script = {t["name"] for t in gen.TEMPLATES}
    assert no_seed == no_script, (
        f"so no seed: {sorted(no_seed - no_script)}; "
        f"so no script: {sorted(no_script - no_seed)}")
