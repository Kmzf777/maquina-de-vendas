"""Contrato de prompt da auditoria de escuta ativa (2026-07-08).

O disparo de 08/07 provou que o "exemplo vencedor" literal vira carimbo: 5 leads
receberam as MESMAS 3 bolhas, e o carimbo atropelou o contexto (Luciano teve que
dizer 3x que fechou a cafeteria; Magda disse "esse celular não é mais da magda" e
a IA salvou "Magda" como nome). Estes testes travam o novo contrato:

- exemplos literais copiáveis FORA do prompt (viram arcos + sementes de tom);
- regra de ANCORAGEM NO NOVO com prioridade sobre qualquer exemplo;
- módulo de empatia para eventos de vida;
- regra de negação de identidade (nunca salvar nome negado);
- playbook de indicação (referral) para negócio vendido/fechado.
"""
from datetime import datetime

from app.agent.prompts.base import build_base_prompt
from app.agent.prompts.valeria_outbound.secretaria import SECRETARIA_PROMPT, TONE_SEEDS
from app.agent.prompts.valeria_outbound.context import build_outbound_first_turn_context

_NOW = datetime(2026, 7, 9, 10, 0, 0)

# O trecho do script antigo que foi copiado byte a byte para 5 leads em 08/07.
_SCRIPT_ANTIGO_SEM_ACENTO = (
    "seu contato tava aqui com a gente e imagino que uma hora voce chegou a se interessar"
)
_SCRIPT_ANTIGO_COM_ACENTO = (
    "seu contato tava aqui com a gente e imagino que uma hora você chegou a se interessar"
)


def _base() -> str:
    return build_base_prompt(None, None, _NOW)


# ---------------------------------------------------------------------------
# base.py — regras novas
# ---------------------------------------------------------------------------

def test_base_tem_regra_de_ancoragem_no_novo():
    prompt = _base()
    assert "ANCORAGEM NO NOVO" in prompt
    assert "prioridade sobre QUALQUER exemplo" in prompt


def test_base_tem_modulo_de_eventos_de_vida():
    prompt = _base()
    assert "EVENTOS DE VIDA" in prompt
    # "que bom" como reação a má notícia foi a falha real do Luciano.
    assert "que bom" in prompt and "vida segue" in prompt


def test_base_tem_regra_de_negacao_de_identidade():
    prompt = _base()
    assert "NEGA" in prompt and "não é mais da" in prompt
    assert "nome NEGADO" in prompt


def test_checklist_cobre_as_tres_regras_novas():
    prompt = _base()
    assert "informação nova" in prompt
    assert "evento de vida" in prompt
    assert "nome negado" in prompt.lower()


# ---------------------------------------------------------------------------
# secretaria.py — arco em vez de script
# ---------------------------------------------------------------------------

def test_script_antigo_removido_da_secretaria():
    assert _SCRIPT_ANTIGO_SEM_ACENTO not in SECRETARIA_PROMPT
    assert _SCRIPT_ANTIGO_COM_ACENTO not in SECRETARIA_PROMPT


def test_secretaria_tem_lei_anti_copia():
    assert "NUNCA reproduza uma semente literalmente" in SECRETARIA_PROMPT


def test_tone_seeds_exportadas_e_curtas():
    # Sementes de TOM: >=3 variações, cada uma substancial o bastante para o
    # detector de eco (>=25 chars), nenhuma contendo o script antigo.
    assert len(TONE_SEEDS) >= 3
    for seed in TONE_SEEDS:
        assert len(seed) >= 25
        assert _SCRIPT_ANTIGO_SEM_ACENTO not in seed


def test_secretaria_tem_contraexemplo_do_luciano():
    assert "não tenho mais a cafeteria" in SECRETARIA_PROMPT


def test_secretaria_tem_discriminador_de_negacao():
    assert "não é mais da" in SECRETARIA_PROMPT


def test_secretaria_tem_playbook_de_referral():
    assert "INDICAÇÃO (REFERRAL)" in SECRETARIA_PROMPT
    assert "quem ficou com" in SECRETARIA_PROMPT


def test_secretaria_preserva_guard_de_cadastro_fantasma():
    # O guard anti-"cadastro fantasma" (cenários A/B) continua de pé.
    assert "cadastro confirmado" in SECRETARIA_PROMPT.lower()
    assert "ABERTURA ORGANICA" in SECRETARIA_PROMPT or "ABERTURA ORGÂNICA" in SECRETARIA_PROMPT


# ---------------------------------------------------------------------------
# context.py — 1º turno outbound sem script copiável
# ---------------------------------------------------------------------------

def test_contexto_frio_nao_carrega_script_literal():
    ctx = build_outbound_first_turn_context(
        "Olá, tudo bem? Falo com Marcelo neste número?", "Marcelo",
    )
    assert _SCRIPT_ANTIGO_SEM_ACENTO not in ctx
    assert _SCRIPT_ANTIGO_COM_ACENTO not in ctx


def test_contexto_frio_exige_reescrita_propria():
    ctx = build_outbound_first_turn_context(
        "Olá, tudo bem? Falo com Marcelo neste número?", "Marcelo",
    )
    assert "NUNCA copie frases prontas" in ctx
