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


def test_objecao_de_preco_mais_nao_bloqueia_suave_a_3_palavras():
    # Achado de mutation testing (revisão 2026-09-17): uma janela NEVER única
    # de 3 palavras pra "mais/bem/bastante/..." bloqueava objeção de preço —
    # o caminho dominante do funil ("mais barato" e afins e a pergunta mais
    # comum) — porque "mais" ficava 2-3 palavras atrás do produto.
    # Intensificador só bloqueia ADJACENTE agora ("mais suave" comparativo),
    # não a distância. Usa VÍRGULA (não "?") de propósito: achado de review
    # posterior — "?" reseta a janela por si só (fix da quebra de
    # bolha/frase), então uma frase com "?" passaria mesmo SEM o split
    # NOUN/ADJACENT e o teste não provaria nada. Vírgula não reseta.
    entrada = "quer algo mais barato, o suave 250g"
    esperado = "quer algo mais barato, o Suave 250g"
    assert normalize_proper_nouns(entrada) == esperado


def test_objecao_de_preco_bem_e_bastante_nao_bloqueiam_a_distancia():
    # Mesmo cuidado com vírgula do teste acima — nenhuma das duas entradas
    # usa "?", pra garantir que é o split NOUN/ADJACENT sendo testado.
    entrada = "quer algo mais barato, o clássico 250g"
    esperado = "quer algo mais barato, o Clássico 250g"
    assert normalize_proper_nouns(entrada) == esperado

    entrada2 = "bastante procurado, o microlote 250g"
    esperado2 = "bastante procurado, o Microlote 250g"
    assert normalize_proper_nouns(entrada2) == esperado2


# ---------------------------------------------------------------------------
# Camada B — NÃO capitaliza (porta de contexto fechada)
# ---------------------------------------------------------------------------

def test_adjacent_nearest_tambem_respeita_quebra_de_bolha():
    # Achado de mutation testing (review seguinte ao boundary-reset das
    # NOUNS): o `nearest` de ADJACENT/determinante usava `[a-z]+` cru sobre
    # o texto inteiro, que ignora pontuacao/quebra de bolha -- entao "mais"
    # de uma bolha ANTERIOR era lido como "a palavra anterior" de um
    # produto em bolha seguinte com determinante colado, e bloqueava por
    # engano (bolha de lista de preco realista neste funil).
    entrada = "qual desses te agrada mais?\n\nsuave 250g - R$28,70"
    esperado = "qual desses te agrada mais?\n\nSuave 250g - R$28,70"
    assert normalize_proper_nouns(entrada) == esperado


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


def test_bridge_nao_escapa_do_gate_never_substantivo():
    # Achado de mutation testing: o bridge "determinante + café/blend" insere
    # 2 tokens entre o NEVER-substantivo e o produto, empurrando "torra" pra
    # 4 palavras de distância — fora de uma janela de 3 aplicada ingenuamente
    # ao texto inteiro. O gate agora olha o texto ANTES do bridge, não entre
    # o bridge e o produto.
    entrada = "a torra do nosso café suave"
    assert normalize_proper_nouns(entrada) == entrada

    entrada2 = "torra do nosso cafe canela"
    assert normalize_proper_nouns(entrada2) == entrada2


def test_never_nouns_nao_atravessa_quebra_de_bolha():
    # Achado de mutation testing (dado real, 90 dias): dos 6 matches
    # distintos de distancia-3 substantivo->produto em producao, 1 era falso
    # bloqueio: "torra" fica na bolha anterior, separada por uma linha em
    # branco, sem relacao com "microlote" na bolha seguinte que tem "o"
    # (determinante) colado. A janela de NOUNS reseta em quebra de bolha/frase.
    entrada = "torra especial\n\no microlote 250g"
    esperado = "torra especial\n\no Microlote 250g"
    assert normalize_proper_nouns(entrada) == esperado


def test_never_nouns_reseta_tambem_em_reticencias_e_dois_pontos():
    # Achado de review posterior: "..." (3 pontos, ja coberto por ".") e "\u2026"
    # (reticencias, um unico codepoint) sao intencao identica -- o prompt
    # sanciona reticencias e o splitter tem regra dedicada preservando "...",
    # entao o modelo emite as duas formas. Dois-pontos tambem reseta (lista
    # de produto apos introducao, forma natural neste agente).
    entrada = "torra especial\u2026 o microlote 250g"
    esperado = "torra especial\u2026 o Microlote 250g"
    assert normalize_proper_nouns(entrada) == esperado

    entrada2 = "de torra especial: o microlote 250g sai R$59"
    esperado2 = "de torra especial: o Microlote 250g sai R$59"
    assert normalize_proper_nouns(entrada2) == esperado2


def test_never_nouns_distancia_3_sem_boundary_continua_bloqueando():
    # Contraprova: SEM quebra de bolha/frase, a janela de 3 continua valendo
    # -- medido em producao (90 dias): distancia-3 ("toque natural de
    # canela") e a forma MAIS comum de uso como especiaria (26 ocorrencias,
    # mais que distancia-2 com 22), nao um caso residual a se descartar.
    #
    # String verbatim de producao (nao "toque natural de canela" -- achado de
    # review posterior: aquela entrada nao tem NENHUM gate de capitalizar
    # disparando -- nem determinante adjacente, nem formato, nem bridge --
    # entao ela passa em janela=3, janela=2 e ate com o NEVER inteiro
    # deletado; nao prova nada sobre o tamanho da janela). Esta tem "250g"
    # (gate de formato) logo depois -- bloqueia com janela=3 ("torra" 3
    # palavras atras) e CAPITALIZARIA com janela=2 (mutation-check abaixo).
    entrada = "torra escura com canela 250g"
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


def test_lead_name_todo_maiusculo_vira_title_case_nao_grita():
    # Dado real (export de 2771 leads nomeados, leads-bling-completo-*.csv):
    # 42,3% de TODOS os nomes, 19,0% dos nomes de pessoa, estão gravados
    # TODO-MAIÚSCULO. Sem este caso especial, a persona (que escreve em
    # minúsculas calmas de propósito) gritaria o nome de 1 em cada 5 leads.
    entrada = "obrigada, VANDA! ate mais"
    esperado = "obrigada, Vanda! ate mais"
    assert normalize_proper_nouns(entrada, lead_name="VANDA") == esperado


def test_lead_name_todo_maiusculo_com_apostrofo_preserva_segunda_maiuscula():
    # Achado de mutation testing: token.capitalize() puro maiusculiza só a
    # PRIMEIRA letra da string inteira e minusculiza o resto -- sobrenome
    # real com apóstrofo saía errado ("D'AVILA" -> "D'avila", perdendo o "A"
    # de Avila). Precisa maiusculizar cada sequência de letras separada.
    entrada = "boa, d'avila, tudo certo"
    esperado = "boa, D'Avila, tudo certo"
    assert normalize_proper_nouns(entrada, lead_name="D'AVILA") == esperado


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


def test_fail_open_com_entrada_nao_string():
    # A chamada de NFC (`unicodedata.normalize`) só é segura DENTRO do try —
    # fora dele, `normalize_proper_nouns(123)` levantava TypeError, o que
    # contradiz o próprio docstring ("qualquer exceção devolve o texto
    # original inalterado").
    entrada = 123
    assert normalize_proper_nouns(entrada) == entrada  # type: ignore[arg-type]


def test_quebra_de_bolha_deixa_frase_de_2_palavras_parcialmente_corrigida():
    # Gap documentado no docstring: a quebra de bolha (\n) entre "serra da" e
    # "canastra" não é reconectada — o `[ \t]+` da Camada A (correto, não
    # deve atravessar bolha) significa que só a segunda linha bate a forma
    # isolada "canastra" -> "Canastra"; a frase completa "Serra da Canastra"
    # não se forma. Comportamento aceito de propósito, não regressão.
    entrada = "cultivado na serra da\ncanastra"
    esperado = "cultivado na serra da\nCanastra"
    assert normalize_proper_nouns(entrada) == esperado
