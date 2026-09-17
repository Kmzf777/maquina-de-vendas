"""normalize_proper_nouns (auditoria 90 dias — 2026-09-17).

A persona da Valéria escreve em minúsculas de propósito (humanização de
WhatsApp), mas o LLM generaliza demais a regra e achata nomes próprios junto.
Medido em produção (90 dias): 22% das auto-menções da Valéria saem "valeria"
em vez de "Valéria", e 18,3% das menções ao nome do lead saem minúsculas. O
caso de maior volume é a saudação de abertura, enviada 340x como
"aqui é a valeria, do comercial da café canastra".

Todos os casos abaixo vieram de mensagens reais de produção.
"""
from app.agent.adherence import normalize_proper_nouns


# ---------------------------------------------------------------------------
# Camada A — léxico inequívoco
# ---------------------------------------------------------------------------

def test_saudacao_de_abertura_340x():
    entrada = "aqui é a valeria, do comercial da café canastra"
    esperado = "aqui é a Valéria, do comercial da Café Canastra"
    assert normalize_proper_nouns(entrada) == esperado


def test_valeria_e_joao_bras_com_lead_name():
    entrada = "perfeito, eliatan, o joao bras que te ajuda"
    esperado = "perfeito, Eliatan, o João Brás que te ajuda"
    assert normalize_proper_nouns(entrada, lead_name="Eliatan") == esperado


def test_sca_sigla():
    entrada = "nosso café tem 84 pontos sca"
    esperado = "nosso café tem 84 pontos SCA"
    assert normalize_proper_nouns(entrada) == esperado


def test_serra_da_canastra_casada_como_frase_unica():
    # "canastra" é sufixo de "serra da canastra" — o finditer consome a frase
    # inteira num só match e nunca reabre a posição interna; não é a ordem
    # das alternativas que garante isso aqui (ver comentário da Camada A).
    entrada = "cultivado na serra da canastra"
    esperado = "cultivado na Serra da Canastra"
    assert normalize_proper_nouns(entrada) == esperado


def test_uberlandia_restaura_acento():
    entrada = "centro de distribuição em uberlândia"
    esperado = "centro de distribuição em Uberlândia"
    assert normalize_proper_nouns(entrada) == esperado


def test_idempotente_aplicar_duas_vezes():
    entrada = "aqui é a valeria, do comercial da café canastra"
    primeira = normalize_proper_nouns(entrada)
    segunda = normalize_proper_nouns(primeira)
    assert primeira == segunda


def test_texto_ja_correto_fica_inalterado():
    entrada = "aqui é a Valéria, do comercial da Café Canastra"
    assert normalize_proper_nouns(entrada) == entrada


def test_canastra_isolado_fora_de_cafe_canastra_e_serra_da_canastra():
    # "canastra" sem "cafe"/"serra da" antes também vira "Canastra".
    entrada = "essa regiao e conhecida como canastra"
    esperado = "essa regiao e conhecida como Canastra"
    assert normalize_proper_nouns(entrada) == esperado


def test_nespresso_e_pratinha():
    entrada = "temos capsulas compativeis com nespresso, vindas de pratinha"
    esperado = "temos capsulas compativeis com Nespresso, vindas de Pratinha"
    assert normalize_proper_nouns(entrada) == esperado


# ---------------------------------------------------------------------------
# Ordem das camadas: A (léxico fixo) tem a palavra final sobre C (nome do
# lead) — bug real achado por mutation testing (2026-09-17): "Valéria" é
# nome próprio comum no Brasil, com 1000+ leads na base. Se C rodasse por
# último, o nome do lead (sem acento, como costuma estar gravado) apagaria de
# volta o acento que A já tinha restaurado.
# ---------------------------------------------------------------------------

def test_lead_chamado_valeria_nao_desfaz_acento_da_valeria_persona():
    entrada = "aqui é a valeria falando"
    esperado = "aqui é a Valéria falando"
    assert normalize_proper_nouns(entrada, lead_name="Valeria") == esperado


def test_lead_chamado_valeria_minusculo_nao_degrada_texto_ja_correto():
    entrada = "aqui é a Valéria falando"
    esperado = "aqui é a Valéria falando"
    assert normalize_proper_nouns(entrada, lead_name="valeria") == esperado


# ---------------------------------------------------------------------------
# Camada B — produtos com porta de contexto (capitaliza)
# ---------------------------------------------------------------------------

def test_suave_precedido_de_determinante_masculino_e_seguido_de_formato():
    entrada = "o suave moído 250g gira em torno de R$28,70"
    esperado = "o Suave moído 250g gira em torno de R$28,70"
    assert normalize_proper_nouns(entrada) == esperado


def test_classico_precedido_de_determinante_masculino():
    entrada = "o clássico é o nosso café com torra mais escura"
    esperado = "o Clássico é o nosso café com torra mais escura"
    assert normalize_proper_nouns(entrada) == esperado


def test_canela_produto_e_canela_ingrediente_na_mesma_frase():
    # Caso mais importante do arquivo: capitaliza o PRIMEIRO ("o canela" =
    # produto), preserva o SEGUNDO ("com canela natural" = ingrediente).
    entrada = "o canela é o nosso café com canela natural"
    esperado = "o Canela é o nosso café com canela natural"
    assert normalize_proper_nouns(entrada) == esperado


def test_microlote_precedido_de_determinante_masculino():
    entrada = "o microlote 250g é a nossa edição limitada"
    esperado = "o Microlote 250g é a nossa edição limitada"
    assert normalize_proper_nouns(entrada) == esperado


def test_formato_sem_determinante_moido_e_250g():
    # Cobre o gate de formato/preço SEM nenhum determinante mascarando o
    # resultado (achado de mutation testing: apagar esse branch inteiro não
    # quebrava nenhum teste anterior porque todos os casos com token de
    # formato também tinham determinante junto).
    entrada = "quero canela moido 250g"
    esperado = "quero Canela moido 250g"
    assert normalize_proper_nouns(entrada) == esperado


def test_formato_sem_determinante_em_graos_e_1kg():
    entrada = "prefiro canela em grãos, tem a opção de 1kg?"
    esperado = "prefiro Canela em grãos, tem a opção de 1kg?"
    assert normalize_proper_nouns(entrada) == esperado


def test_bridge_determinante_mais_cafe_antes_do_produto():
    # Requisito novo (dado de produção, 45 dias): "determinante + café/blend
    # + produto" aparece 68x e não era coberto pelo gate adjacente puro.
    entrada = "o nosso café suave é incrível"
    esperado = "o nosso café Suave é incrível"
    assert normalize_proper_nouns(entrada) == esperado


# ---------------------------------------------------------------------------
# Camada B — NÃO capitaliza (porta de contexto fechada)
# ---------------------------------------------------------------------------

def test_torra_suave_nao_capitaliza():
    entrada = "esse café tem uma torra suave"
    assert normalize_proper_nouns(entrada) == entrada


def test_notas_de_canela_nao_capitaliza():
    entrada = "notas de canela e caramelo"
    assert normalize_proper_nouns(entrada) == entrada


def test_com_canela_natural_nao_capitaliza():
    entrada = "com canela natural"
    assert normalize_proper_nouns(entrada) == entrada


def test_da_canela_feminino_nao_capitaliza():
    # "da" é feminino — deliberadamente fora da lista de determinantes.
    entrada = "a adição natural da canela"
    assert normalize_proper_nouns(entrada) == entrada


def test_sabor_mais_classico_nao_capitaliza():
    entrada = "um sabor mais clássico"
    assert normalize_proper_nouns(entrada) == entrada


def test_sabor_microlote_never_precede_bloqueia_mesmo_com_formato_depois():
    # "sabor" (NEVER) precede diretamente; NEVER tem precedência mesmo que a
    # regra de "seguido de formato" (250g) também case.
    entrada = "um sabor microlote 250g diferente"
    assert normalize_proper_nouns(entrada) == entrada


def test_notas_de_canela_com_formato_depois_nao_capitaliza():
    # "notas de" é a construção clássica de nota de degustação — NEVER
    # precisa olhar 2 palavras para trás (não só a adjacente "de") para
    # pegar "notas", mesmo com "250g" (gate de formato) logo depois.
    entrada = "notas de canela 250g"
    assert normalize_proper_nouns(entrada) == entrada


def test_perfil_de_canela_moido_nao_capitaliza():
    entrada = "perfil de canela moido"
    assert normalize_proper_nouns(entrada) == entrada


def test_torra_do_canela_nao_capitaliza_mesmo_com_determinante_adjacente():
    # "do" é determinante adjacente (dispararia a regra de capitalizar
    # sozinho), mas "torra" 2 palavras atrás é NEVER e tem precedência.
    entrada = "torra do canela"
    assert normalize_proper_nouns(entrada) == entrada


# ---------------------------------------------------------------------------
# Camada C — nome do lead (dinâmico)
# ---------------------------------------------------------------------------

def test_lead_name_minusculo_no_banco_e_capitalizado_pela_regra():
    entrada = "funciona assim, vanda"
    esperado = "funciona assim, Vanda"
    assert normalize_proper_nouns(entrada, lead_name="vanda") == esperado


def test_lead_name_primeiro_e_ultimo_token():
    entrada = "boa, jorge eliseu, que bom te ver"
    esperado = "boa, Jorge Eliseu, que bom te ver"
    assert normalize_proper_nouns(entrada, lead_name="Jorge Eliseu") == esperado


def test_lead_name_3_caracteres_aplica():
    entrada = "combinado, ana, ate mais"
    esperado = "combinado, Ana, ate mais"
    assert normalize_proper_nouns(entrada, lead_name="Ana") == esperado


def test_lead_name_2_caracteres_nao_aplica():
    entrada = "combinado, jo, ate mais"
    assert normalize_proper_nouns(entrada, lead_name="Jo") == entrada


def test_lead_name_none_layer_c_nao_roda_mas_a_e_b_funcionam():
    entrada = "aqui é a valeria, do comercial da café canastra"
    esperado = "aqui é a Valéria, do comercial da Café Canastra"
    assert normalize_proper_nouns(entrada, lead_name=None) == esperado


def test_lead_name_colide_com_palavra_comum_capitaliza_mesmo_assim():
    # Efeito colateral ACEITO de propósito (ver comentário em
    # _title_case_lead_name): falso-positivo raro e de baixo custo — não vale
    # a complexidade de desambiguar nome de lead vs. palavra comum.
    entrada = "a rosa dos ventos"
    esperado = "a Rosa dos ventos"
    assert normalize_proper_nouns(entrada, lead_name="Rosa") == esperado


def test_lead_name_preserva_caixa_interna_apos_primeira_letra():
    # "Jose-Maria" tem uma maiúscula legítima no meio (o "M" de Maria) — só a
    # primeira letra do token é forçada; achado de mutation testing: forçar
    # .lower() no resto degradava um nome já corretamente gravado.
    entrada = "boa, jose-maria, tudo certo"
    esperado = "boa, Jose-Maria, tudo certo"
    assert normalize_proper_nouns(entrada, lead_name="Jose-Maria") == esperado


# ---------------------------------------------------------------------------
# Guards estruturais (span walk, NFC, quebra de linha, URL/e-mail)
# ---------------------------------------------------------------------------

def test_reversed_span_walk_com_replacement_de_tamanho_diferente():
    # Dois hits do léxico, cada um com espaço duplo interno (colapsa para um
    # espaço no canônico — tamanho do replacement != tamanho do match).
    # Achado de mutation testing: trocar `reversed(matches)` por `matches`
    # não quebrava nenhum teste anterior porque todos tinham replacement do
    # mesmo tamanho do match.
    entrada = "da cafe  canastra e da serra  da  canastra"
    esperado = "da Café Canastra e da Serra da Canastra"
    assert normalize_proper_nouns(entrada) == esperado


def test_nfc_normaliza_entrada_ja_decomposta_nfd():
    import unicodedata

    entrada = unicodedata.normalize(
        "NFD", "aqui é a valeria, do comercial da café canastra"
    )
    esperado = "aqui é a Valéria, do comercial da Café Canastra"
    assert normalize_proper_nouns(entrada) == esperado


def test_lexico_nao_atravessa_quebra_de_linha_entre_bolhas():
    # A persona quebra bolhas do WhatsApp propositalmente em "\n" — o guard
    # não pode juntar duas bolhas numa frase só ao aplicar a forma canônica.
    entrada = "do comercial da cafe\ncanastra"
    esperado = "do comercial da cafe\nCanastra"
    assert normalize_proper_nouns(entrada) == esperado


def test_nao_capitaliza_dentro_de_email():
    entrada = "para duvidas, escreva pra valeria@cafecanastra.com"
    assert normalize_proper_nouns(entrada) == entrada


# ---------------------------------------------------------------------------
# Fail-open / edge cases
# ---------------------------------------------------------------------------

def test_texto_vazio_retorna_vazio():
    assert normalize_proper_nouns("") == ""


def test_texto_none_retorna_none():
    assert normalize_proper_nouns(None) is None  # type: ignore[arg-type]


def test_lead_name_vazio_nao_quebra():
    entrada = "combinado, ate mais"
    assert normalize_proper_nouns(entrada, lead_name="") == entrada


def test_lead_name_so_espacos_nao_quebra():
    entrada = "combinado, ate mais"
    assert normalize_proper_nouns(entrada, lead_name="   ") == entrada


def test_fail_open_quando_camada_lanca_excecao(monkeypatch):
    # Achado de mutation testing: trocar o `except Exception: return text`
    # por `raise` não quebrava nenhum teste anterior — esse é o
    # comportamento mais importante de pinar num guard do caminho de envio.
    import app.agent.adherence as adherence

    def _boom(_text):
        raise RuntimeError("boom")

    monkeypatch.setattr(adherence, "_apply_proper_noun_lexicon", _boom)
    entrada = "aqui é a valeria, do comercial da café canastra"
    assert normalize_proper_nouns(entrada) == entrada
