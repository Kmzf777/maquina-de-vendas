"""Proibição de travessões + endurecimento da blacklist de acks — auditoria 2026-06-24.

Rodada outbound real: a Valéria usou travessões ("—") e as palavras banidas
("perfeito"/"show"/"entendo"/"que bacana") mesmo com a regra anti-preenchimento global.
Causa-raiz: os PRÓPRIOS EXEMPLOS do prompt modelavam o comportamento (ex.: secretaria
"perfeito, cadastro confirmado ... falo contigo por aqui — a gente é a torrefação...").
Estes testes travam (1) a regra explícita anti-travessão, (2) a blacklist crítica com
penalidade e (3) a remoção dos exemplos que contradiziam a regra.
"""
from datetime import datetime


def _p():
    from app.agent.prompts.base import build_base_prompt
    return build_base_prompt(None, None, datetime(2026, 6, 24, 14, 0))


# --- Correção 1: proibição de travessões -----------------------------------

def test_base_proibe_travessoes():
    p = _p()
    low = p.lower()
    assert "travess" in low                      # travessões / travessao
    assert "meia-risca" in low or "hifens" in low or "hifen" in low
    assert "fluida" in low or "fluido" in low     # "escreva de forma fluida"


# --- Correção 3: blacklist crítica com penalidade ---------------------------

def test_base_blacklist_critica_nomeia_palavras_e_penalidade():
    p = _p()
    assert "BLACK-LIST" in p or "BLACKLIST" in p
    low = p.lower()
    assert "reprovad" in low                       # "a conversa será reprovada"
    for w in ("entendo", "bacana", "show", "perfeito"):
        assert w in low, f"a blacklist deve nomear explicitamente '{w}'"


# --- Contradições removidas (exemplos que ensinavam as palavras banidas) ----

def test_base_nao_endossa_palavras_banidas():
    p = _p()
    # a antiga lista de "Vocabulario" que endossava as 4 palavras saiu
    assert '"perfeito", "com certeza", "entendo", "bacana"' not in p
    # exemplos POSITIVOS que usavam as palavras banidas foram reescritos
    assert "que projeto bacana" not in p
    assert "bacana que voce ta nesse ramo" not in p
    assert "bacana, me conta mais como é o projeto" not in p
    assert "5 anos, bacana" not in p
    assert "bacana, o que te levou a entrar nesse mercado" not in p
    assert "bacana. qual o volume" not in p


# --- Persona outbound: exemplos que vazaram travessão + acks banidos --------

def test_secretaria_outbound_sem_travessao_e_sem_acks_banidos():
    from app.agent.prompts.valeria_outbound.secretaria import SECRETARIA_PROMPT
    assert "perfeito, cadastro confirmado" not in SECRETARIA_PROMPT
    assert "show, cadastro confirmado" not in SECRETARIA_PROMPT
    # o exemplo de confirmação não usa mais o em-dash colando duas ideias
    assert "falo contigo por aqui —" not in SECRETARIA_PROMPT
    assert "falo contigo por aqui  —" not in SECRETARIA_PROMPT


def test_atacado_outbound_sem_ack_perfeito_solto():
    from app.agent.prompts.valeria_outbound.atacado import ATACADO_PROMPT
    assert "perfeito, e otimo que voce ja ta de olho" not in ATACADO_PROMPT


# --- Isolamento de escopo: INBOUND não pode contradizer a blacklist global --
# (a blacklist mora no base.py compartilhado; os exemplos few-shot do inbound que
#  MODELAVAM a Valéria dizendo "show"/"que bacana" como SUA saída foram corrigidos.
#  As listas que reconhecem o que o LEAD diz permanecem — não são saída da Valéria.)

def test_inbound_secretaria_nao_modela_valeria_dizendo_banido():
    from app.agent.prompts.valeria_inbound.secretaria import SECRETARIA_PROMPT
    assert 'Assistant: "show"' not in SECRETARIA_PROMPT
    assert '✅ "que bacana"' not in SECRETARIA_PROMPT
    assert '"show, entao sua demanda' not in SECRETARIA_PROMPT


def test_inbound_consumo_despedida_sem_show():
    from app.agent.prompts.valeria_inbound.consumo import CONSUMO_PROMPT
    assert '"show, aproveita o cupom"' not in CONSUMO_PROMPT


def test_outbound_consumo_despedida_sem_show():
    from app.agent.prompts.valeria_outbound.consumo import CONSUMO_PROMPT
    assert '"show, aproveita o cupom"' not in CONSUMO_PROMPT


def test_base_exemplo_bolha_curta_sem_show():
    """base.py não pode citar 'show' como exemplo de bolha curta permitida (contradiz a blacklist)."""
    p = _p()
    assert '("boa", "fechou", "show")' not in p
