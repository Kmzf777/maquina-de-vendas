# scripts/reativacao/generate_sql.py
"""Gera o SQL da preparacao de reativacao. Nao executa nada.

O artefato revisavel e o proprio arquivo .sql: ele e inspecionado antes de rodar
via psql, dentro de uma transacao, depois do pg_dump. Ver
docs/superpowers/plans/2026-08-08-reativacao-crm-preparacao.md
"""
import argparse
import csv
import json
import os
import sys

import transform

LOTE = "reativacao_bling_2026-08-10"
ORIGEM = "reativacao_bling"
JOAO_UUID = "1c3c78ed-ef47-4dca-9a63-2052f28e8fd6"
CANAL_JOAO = "553491461669"
AUTOR_NOTA = "Sistema — Reativação Bling"

# Guardrail: o SQL gerado nunca pode tocar o disparo.
TABELAS_PROIBIDAS = ("broadcasts", "broadcast_leads")

# Guardrail: colunas que nunca podem ser sobrescritas nos leads pre-existentes.
COLUNAS_INTOCAVEIS = ("stage", "status", "human_control", "ai_enabled")

# Decisao D7 do spec: recebem lead + nota, mas ficam fora da campanha.
MOTIVOS_EXCLUSAO = {
    "5511996057340": "operação de café encerrada — o cliente avisou",
    "5511989374541": "o número é o atendimento automático da loja",
    "5516997442292": "LEAD QUENTE — pediu portfólio e cápsulas/drip; responder o pedido dele, não disparar template",
    "5554996324731": "declinou com gatilho — retomar quando o estoque dela baixar",
}

# Decisao D9: telefone a normalizar antes dos inserts.
NORMALIZACOES = (("11981154002", "5511981154002"),)

# Duplicatas logicas no CRM: a mesma pessoa cadastrada duas vezes (uma com o
# prefixo 55, outra sem), com o historico dividido entre os dois registros.
# Nao ha como escolher o registro certo sem mesclar os dados primeiro, entao
# ficam de fora deste lote — nem lead, nem nota. Serao tratados apos o merge.
DUPLICATAS_EXCLUIDAS = (
    "5511995589320",  # Divina Terra - Bauru
    "5512996525336",  # Armazem Di Vino
    "5527999646131",  # Divina Terra - Vitoria
    "5534992423031",  # Four House — um dos registros tem opt_out=TRUE
    "5544991542351",  # Emporio Vidori
    "5547991301453",  # Mercado Bia
    "5551996905247",  # Divina Terra Osorio
    "5554996324731",  # Divina Terra - BALNEARIO CAMBORIU
    "5562996968292",  # Antenor Jose de Pinheiro Santos
    "5567999777377",  # Welinton Da Silva Ferreira
)

# Campos que vem da planilha master, nao do CSV de disparo.
CAMPOS_DA_MASTER = ("qtd_nfe", "orcamentos", "valor_vencido", "titulos_vencidos",
                    "dias_atraso_max", "qtd_top1")


def sql_literal(valor):
    """Escapa para literal SQL; vazio/None viram NULL."""
    if valor is None:
        return "NULL"
    texto = str(valor).strip()
    if not texto:
        return "NULL"
    return "'" + texto.replace("'", "''") + "'"


def _metadata_json(dados):
    return {
        "origem": ORIGEM,
        "lote": LOTE,
        "id_bling": (dados.get("id_bling") or "").strip(),
        "icp_score": (dados.get("icp_score") or "").strip(),
        "phone_raw": (dados.get("whatsapp") or "").strip(),
    }


def gerar_insert_lead(dados, nome_crm):
    """INSERT idempotente de um lead novo.

    Grava "criado_por_lote" no metadata — marcador explicito, distinto de
    "lote" (que tambem e escrito por gerar_update_conservador em leads
    pre-existentes). O rollback usa esse marcador para saber com certeza
    quem este lote CRIOU, em vez de inferir isso por "nao tem mensagens"
    (proxy falsa: leads pre-existentes tambem podem nao ter mensagens).
    gerar_update_conservador NUNCA deve escrever essa chave.

    Fix round 3 (C3, Important): ai_enabled entra como literal 'false' na
    VALUES, nunca via sql_literal (que renderizaria a STRING 'False', nao o
    booleano). leads.ai_enabled e NOT NULL DEFAULT TRUE — sem isso, os 236
    leads novos nascem com ai_enabled=true, e o motor de automacao
    (backend/app/automation/triggers.py, stage_stagnation/no_sale_in_stage)
    seleciona por "ai_enabled = true AND stage = <filtro>" sem checar
    leads.opt_out. Nenhuma campanha esta ativa hoje, mas uma futura pegaria
    esses leads.
    """
    phone = transform.normalizar_telefone(dados.get("whatsapp"))
    nome = transform.escolher_saudacao(nome_crm, dados.get("nome"))
    metadata_dict = _metadata_json(dados)
    metadata_dict["criado_por_lote"] = LOTE
    metadata = json.dumps(metadata_dict, ensure_ascii=False)
    return (
        "INSERT INTO leads (phone, name, company, stage, status, channel, "
        "assigned_to, cnpj, razao_social, nome_fantasia, email, endereco, metadata, "
        "ai_enabled)\n"
        "VALUES (%s, %s, %s, 'pending', 'imported', %s, %s::uuid, %s, %s, %s, %s, %s, "
        "%s::jsonb, false)\n"
        "ON CONFLICT (phone) DO NOTHING;" % (
            sql_literal(phone),
            sql_literal(nome),
            sql_literal(dados.get("razao_social") or dados.get("nome")),
            sql_literal(CANAL_JOAO),
            sql_literal(JOAO_UUID),
            sql_literal(dados.get("cpf_cnpj")),
            # Fallback igual ao de "company": 202 das 276 linhas trazem
            # razao_social vazia no CSV de disparo, com o nome legal so em
            # "nome". Sem o fallback, razao_social ficaria NULL indevidamente.
            sql_literal(dados.get("razao_social") or dados.get("nome")),
            sql_literal(dados.get("saudacao")),
            sql_literal(dados.get("email")),
            sql_literal("/".join(p for p in [(dados.get("cidade") or "").strip(),
                                             (dados.get("uf") or "").strip()] if p)),
            sql_literal(metadata),
        )
    )


def gerar_update_conservador(dados, tem_dono):
    """UPDATE que so preenche o que esta vazio (decisao D5 do spec).

    Nunca emite as COLUNAS_INTOCAVEIS. metadata recebe merge com ||, nunca
    substituicao. assigned_to so entra quando o lead nao tem dono.
    """
    phone = transform.normalizar_telefone(dados.get("whatsapp"))
    metadata = json.dumps(_metadata_json(dados), ensure_ascii=False)
    local = "/".join(p for p in [(dados.get("cidade") or "").strip(),
                                 (dados.get("uf") or "").strip()] if p)
    sets = [
        "cnpj = COALESCE(NULLIF(cnpj, ''), %s)" % sql_literal(dados.get("cpf_cnpj")),
        # Mesmo fallback do INSERT (D5 lista razao_social como campo a
        # preencher): 202 das 276 linhas trazem razao_social vazia no CSV
        # de disparo, com o nome legal so em "nome".
        "razao_social = COALESCE(NULLIF(razao_social, ''), %s)" % sql_literal(
            dados.get("razao_social") or dados.get("nome")),
        "nome_fantasia = COALESCE(NULLIF(nome_fantasia, ''), %s)" % sql_literal(dados.get("saudacao")),
        "email = COALESCE(NULLIF(email, ''), %s)" % sql_literal(dados.get("email")),
        "endereco = COALESCE(NULLIF(endereco, ''), %s)" % sql_literal(local),
        "metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb" % sql_literal(metadata),
    ]
    if not tem_dono:
        sets.append("assigned_to = COALESCE(assigned_to, %s::uuid)" % sql_literal(JOAO_UUID))
    return "UPDATE leads SET\n  %s\nWHERE phone = %s;" % (
        ",\n  ".join(sets), sql_literal(phone))


def gerar_insert_nota(dados, nome_crm):
    """Nota de briefing, so se ainda nao existir a nota deste lote."""
    phone = transform.normalizar_telefone(dados.get("whatsapp"))
    dados_briefing = dict(dados)
    dados_briefing["saudacao"] = transform.escolher_saudacao(nome_crm, dados.get("nome"))
    conteudo = transform.montar_briefing(dados_briefing)
    return (
        "INSERT INTO lead_notes (lead_id, author, content)\n"
        "SELECT l.id, %s, %s\n"
        "FROM leads l\n"
        "WHERE l.phone = %s\n"
        "  AND NOT EXISTS (\n"
        "    SELECT 1 FROM lead_notes n\n"
        "    WHERE n.lead_id = l.id AND n.content LIKE %s\n"
        "  );" % (
            sql_literal(AUTOR_NOTA),
            sql_literal(conteudo),
            sql_literal(phone),
            sql_literal("%" + LOTE + "%"),
        )
    )


def gerar_update_optout(telefone, quando, disse):
    """Marca opt_out e registra a evidencia no metadata.

    O metadata leva "optout_lote" junto com a evidencia (Finding 2 do fix
    round 1): sem isso, o rollback de opt-outs nao tem como saber que
    opt-out foi aplicado POR ESTE lote, e desfaria opt-outs de qualquer
    lote — reabrindo contato com quem pediu para nao ser contactado em
    outra campanha.

    Fix round 3 (C1, CRITICAL): a chave e "optout_lote", NUNCA "lote". Uma
    versao anterior gravava "lote" aqui, que e a MESMA chave que
    gerar_insert_lead/gerar_update_conservador usam para marcar leads deste
    lote — o rodape de verificacao contava "leads WHERE metadata->>'lote' ="
    e os 51 opt-outs (100% disjuntos dos 276 leads/notas) inflavam essa
    contagem para 327, disparando o RAISE EXCEPTION e fazendo rollback de
    TUDO (276 leads + 276 notas perdidos). "optout_lote" e uma chave
    distinta que so este UPDATE escreve — nunca colide com a contagem de
    leads, que agora chaveia em metadata.origem (ver _gerar_rodape).
    """
    phone = transform.normalizar_telefone(telefone)
    evidencia = json.dumps(
        {
            "optout_quando": quando,
            "optout_disse": (disse or "")[:200],
            "optout_fonte": "mensagem_do_cliente",
            "optout_lote": LOTE,
        },
        ensure_ascii=False,
    )
    return (
        "UPDATE leads SET\n"
        "  opt_out = true,\n"
        "  metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb\n"
        "WHERE regexp_replace(phone, '[^0-9]', '', 'g') IN (%s, %s)\n"
        "  AND opt_out IS NOT TRUE;" % (
            sql_literal(evidencia), sql_literal(phone), sql_literal(phone[2:] if phone.startswith("55") else phone))
    )


def gerar_normalizacao_telefone(antigo, novo):
    """Corrige um phone para E.164, sem colidir com registro existente (D9).

    Fix round 3 (I3, Important): o UPDATE e guardado por
    "NOT EXISTS (... outro.phone = novo)" — se outro lead JA tiver o
    telefone novo, o UPDATE silenciosamente nao faz nada (0 linhas, sem
    erro). O INSERT do lead que vem depois entao colide em
    ON CONFLICT (phone) DO NOTHING com esse "outro" lead, e a nota de
    briefing financeiro de um cliente vai para o card de um estranho, sem
    aviso nenhum. O bloco DO $$ abaixo falha ALTO, dentro da transacao,
    se depois do UPDATE nao existir exatamente 1 registro com o telefone
    novo e 0 com o antigo.
    """
    update = (
        "UPDATE leads SET phone = %s\n"
        "WHERE phone = %s\n"
        "  AND NOT EXISTS (SELECT 1 FROM leads outro WHERE outro.phone = %s);" % (
            sql_literal(novo), sql_literal(antigo), sql_literal(novo))
    )
    assercao = (
        "DO $$\n"
        "DECLARE n_novo integer; n_antigo integer;\n"
        "BEGIN\n"
        "  SELECT count(*) INTO n_novo FROM leads WHERE phone = %s;\n"
        "  SELECT count(*) INTO n_antigo FROM leads WHERE phone = %s;\n"
        "  IF n_novo <> 1 OR n_antigo <> 0 THEN\n"
        "    RAISE EXCEPTION "
        "'normalizacao de telefone falhou (%s -> %s): esperado 1 registro no "
        "novo e 0 no antigo, encontrado novo=%%, antigo=%%', n_novo, n_antigo;\n"
        "  END IF;\n"
        "END $$;"
    ) % (sql_literal(novo), sql_literal(antigo), antigo, novo)
    return update + "\n\n" + assercao


# NOTA (defeito do brief task-6): o cabecalho de referencia do brief citava
# literalmente "broadcasts/broadcast_leads" no comentario, o que quebra a
# propria garantia que o guardrail TABELAS_PROIBIDAS deveria proteger (o teste
# test_nunca_menciona_tabelas_de_disparo varre o SQL inteiro, comentarios
# inclusive). Reformulado para nao nomear as tabelas proibidas, preservando a
# mensagem "este arquivo nao cria disparo".
CABECALHO = """-- Preparacao da campanha de reativacao — lote %s
-- Gerado por scripts/reativacao/generate_sql.py. NAO editar a mao.
-- Spec:  docs/superpowers/specs/2026-08-08-reativacao-crm-preparacao-design.md
-- Plano: docs/superpowers/plans/2026-08-08-reativacao-crm-preparacao.md
--
-- PRE-REQUISITO: pg_dump feito. Rodar com:
--   psql -U postgres -v ON_ERROR_STOP=1 -f preparar.sql
--
-- Este arquivo NAO cria disparo. Nenhuma escrita nas tabelas de campanha/fila
-- de envio (fora do escopo desta preparacao de dados).
\\set ON_ERROR_STOP on
BEGIN;
-- Fix round 3 (I6, Important): o texto das notas usa REATIVAÇÃO, há,
-- Orçamentos, ⚠, travessões — psql deriva client_encoding do locale do
-- container/terminal, e sem isso a nota pode chegar corrompida no card do
-- vendedor.
SET client_encoding TO 'UTF8';
""" % LOTE

def _bloco_verificacao(rotulo, expressao_where, esperado):
    """Um DO $$ ... $$ que aborta a transacao (RAISE EXCEPTION) se a
    contagem nao bater com o esperado.

    Fix round 1, Finding 3 (Important): um SELECT count(*) que so faz
    \\echo nao impede o COMMIT quando a contagem esta errada — psql -f roda
    o arquivo inteiro de uma vez, e o COMMIT roda na mesma passada em que a
    contagem errada foi so exibida. Precisa de algo que force o rollback da
    transacao sozinho, num banco sem backup.
    """
    return (
        "\\echo '--- %s (esperado: %d) ---'\n"
        "DO $$\n"
        "DECLARE n integer;\n"
        "BEGIN\n"
        "  SELECT count(*) INTO n FROM %s;\n"
        "  IF n <> %d THEN\n"
        "    RAISE EXCEPTION 'esperado %d %s, encontrado %%', n;\n"
        "  END IF;\n"
        "END $$;"
    ) % (rotulo, esperado, expressao_where, esperado, esperado, rotulo)


def _gerar_rodape(qtd_leads_esperado, qtd_notas_esperado, qtd_optouts_esperado):
    """Rodape com as 3 verificacoes de contagem + COMMIT.

    Os numeros esperados sao parametros derivados de len(novos) +
    len(existentes) e len(optouts) em montar_arquivo — nunca literais fixos
    do lote atual — para que o check nunca possa divergir da realidade do
    que de fato foi passado para montar_arquivo.

    Fix round 3 (C1, CRITICAL): a contagem de "leads do lote" NAO pode mais
    chavear so em metadata->>'lote' — os 51 UPDATEs de opt-out sao 100%
    disjuntos dos 276 leads/notas, mas (antes deste fix) tambem escreviam
    "lote" no metadata, inflando a contagem para 236+40+51=327 e disparando
    o RAISE EXCEPTION (rollback de tudo, leads e notas inclusos). A chave
    "origem" (metadata.origem='reativacao_bling') e escrita SO por
    gerar_insert_lead/gerar_update_conservador, nunca por
    gerar_update_optout — combinada com "lote" (que agora e exclusiva
    dessas duas funcoes, ja que o opt-out passou a usar "optout_lote"), fica
    impossivel para as duas contagens colidirem de novo, mesmo se um lote
    futuro reusar a mesma constante ORIGEM.
    """
    blocos = [
        "-- ── Verificacao (dentro da transacao; aborta se a contagem nao bater) ─────",
        _bloco_verificacao(
            "leads do lote",
            "leads WHERE metadata->>'origem' = %s AND metadata->>'lote' = %s" % (
                sql_literal(ORIGEM), sql_literal(LOTE)),
            qtd_leads_esperado,
        ),
        _bloco_verificacao(
            "notas do lote",
            "lead_notes WHERE content LIKE %s" % sql_literal("%" + LOTE + "%"),
            qtd_notas_esperado,
        ),
        _bloco_verificacao(
            "opt-outs marcados",
            "leads WHERE opt_out AND metadata->>'optout_lote' = %s AND metadata->>'optout_fonte' = 'mensagem_do_cliente'"
            % sql_literal(LOTE),
            qtd_optouts_esperado,
        ),
        "COMMIT;",
    ]
    return "\n\n".join(blocos) + "\n"


def montar_arquivo(novos, existentes, optouts, normalizacoes):
    """SQL completo, em transacao unica.

    Ordem importa: normalizacoes de telefone vem antes dos INSERTs, senao o
    registro com telefone curto viraria duplicata logica do novo.
    """
    partes = [CABECALHO]

    partes.append("\n-- ── 1. Normalizacao de telefone (decisao D9) ──────────────────────────────")
    for antigo, novo in normalizacoes:
        partes.append(gerar_normalizacao_telefone(antigo, novo))

    partes.append("\n-- ── 2. Leads novos ────────────────────────────────────────────────────────")
    for dados, nome_crm, _ in novos:
        partes.append(gerar_insert_lead(dados, nome_crm))

    partes.append("\n-- ── 3. Leads existentes: preencher apenas vazios (decisao D5) ─────────────")
    for dados, _nome_crm, tem_dono in existentes:
        partes.append(gerar_update_conservador(dados, tem_dono))

    partes.append("\n-- ── 4. Notas de briefing ──────────────────────────────────────────────────")
    for dados, nome_crm, _ in list(novos) + list(existentes):
        partes.append(gerar_insert_nota(dados, nome_crm))

    partes.append("\n-- ── 5. Opt-outs pendentes ─────────────────────────────────────────────────")
    for telefone, quando, disse in optouts:
        partes.append(gerar_update_optout(telefone, quando, disse))

    qtd_leads_e_notas_esperado = len(novos) + len(existentes)
    partes.append(_gerar_rodape(qtd_leads_e_notas_esperado, qtd_leads_e_notas_esperado, len(optouts)))
    return "\n\n".join(partes)


def montar_rollback():
    """Desfaz exatamente este lote.

    Fix round 1, Finding 1 (CRITICAL): o sinal PRIMARIO de "este lote criou
    este lead" e o marcador explicito metadata.criado_por_lote — escrito
    apenas por gerar_insert_lead, nunca por gerar_update_conservador.
    "NOT EXISTS (messages)" e mantido como uma SEGUNDA rede de seguranca
    independente, nao mais como sinal primario: em produção, 3 dos 40 leads
    pre-existentes (um deles ja secretaria/active) nao tinham mensagem
    nenhuma e seriam apagados por engano se "sem mensagem" fosse o unico
    criterio. Um lead pre-existente que recebeu merge no metadata (tem
    metadata.lote mas NAO tem metadata.criado_por_lote) sobrevive sempre.

    Fix round 1, Finding 2 (Important): o UPDATE que desfaz opt-out so pode
    atingir opt-outs aplicados por ESTE lote, senao um rollback futuro
    reabriria contato com quem pediu para nao ser contactado em OUTRO lote.

    Fix round 3 (C1/I2): o UPDATE de opt-out agora chaveia em
    metadata->>'optout_lote' (nunca 'lote' — essa chave e exclusiva de
    gerar_insert_lead/gerar_update_conservador desde o fix do C1) e limpa as
    proprias chaves de evidencia (optout_quando/optout_disse/optout_fonte/
    optout_lote) na MESMA instrucao que desmarca opt_out, em vez de deixar
    para o UPDATE de metadata generico mais abaixo. O UPDATE de metadata
    generico (chaves lote/origem/id_bling/icp_score/criado_por_lote) passa a
    scopar por origem+lote juntos: so gerar_insert_lead/gerar_update_conservador
    escrevem origem='reativacao_bling', entao esse UPDATE nunca mais pode
    colidir com os opt-outs (que sao 100% disjuntos dos 276 leads/notas) nem
    apagar por engano um metadata.origem pre-existente ('terceirizacao'/
    'atacado', 344 usos em producao) de um lead que so recebeu opt-out.
    """
    return """-- Rollback do lote %(lote)s
-- Remove SO o que este lote criou. Leads pre-existentes que receberam merge de
-- metadata ou nota permanecem — apenas a nota e o metadata do lote saem.
\\set ON_ERROR_STOP on
BEGIN;
SET client_encoding TO 'UTF8';

DELETE FROM lead_notes WHERE content LIKE '%%%(lote)s%%';

UPDATE leads
SET opt_out = false,
    metadata = metadata - 'optout_quando' - 'optout_disse' - 'optout_fonte' - 'optout_lote'
WHERE opt_out AND metadata->>'optout_lote' = '%(lote)s' AND metadata->>'optout_fonte' = 'mensagem_do_cliente';

DELETE FROM leads l
WHERE l.metadata->>'criado_por_lote' = '%(lote)s'
  AND NOT EXISTS (SELECT 1 FROM messages m WHERE m.lead_id = l.id);

UPDATE leads SET metadata = metadata - 'lote' - 'origem' - 'id_bling' - 'icp_score' - 'criado_por_lote'
WHERE metadata->>'origem' = '%(origem)s' AND metadata->>'lote' = '%(lote)s';

\\echo '--- deve retornar 0 ---'
SELECT count(*) AS restantes FROM lead_notes WHERE content LIKE '%%%(lote)s%%';

COMMIT;
""" % {"lote": LOTE, "origem": ORIGEM}


def carregar_disparo(caminho):
    with open(caminho, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def carregar_master(caminho):
    """id_bling -> dict, para puxar os campos que o CSV de disparo nao tem."""
    with open(caminho, encoding="utf-8-sig", newline="") as fh:
        return {linha["id_bling"]: linha for linha in csv.DictReader(fh)}


def carregar_nomes_crm(caminho):
    """Le o TSV 'telefone<TAB>nome' dos leads que ja existem no CRM.

    Fix round 1, Finding 1 (CRITICAL): a extracao de origem (psql \\copy)
    pode gravar a sequencia LITERAL de dois caracteres "\\t" em vez de um TAB
    real (bug tipico de usar E'\\t' errado no \\copy). O parser tolera os
    dois formatos: tenta um TAB real primeiro; se a linha nao tiver TAB real
    mas tiver a sequencia literal "\\t", usa ela.

    Um CRM vazio nao e um estado plausivel (a base tem milhares de leads) —
    se nenhuma linha for parseavel, explode com o caminho do arquivo e a
    primeira linha bruta, em vez de devolver silenciosamente um dict vazio
    que faria o script tratar TODOS os leads existentes como novos.

    Fix round 3 (C2, CRITICAL): a chave do dict devolvido e o telefone
    NORMALIZADO (via transform.normalizar_telefone), nao o texto crudo do
    banco. O banco guarda phone em 10/11/12/13 digitos verbatim (extraido
    via regexp_replace no runbook), mas enriquecer() consulta este dict com
    o telefone JA normalizado (13 digitos). Com a chave crua, um lead como
    Atma/Fernando ("11981154002", 11 digitos) nunca era encontrado pela
    chave normalizada ("5511981154002") e caia em "novos" — e como o passo 1
    (normalizacao D9) ja tinha renomeado a linha do banco para
    "5511981154002", o INSERT subsequente colidia em
    "ON CONFLICT (phone) DO NOTHING" e nao escrevia metadata/assigned_to
    nenhum, nem disparava o UPDATE conservador. Producao tem 212 leads com
    10 digitos e 191 com 11 — qualquer um deles reaparecendo numa lista
    futura sofreria o mesmo defeito, so que criando uma DUPLICATA real (a
    string normalizada e diferente da crua, entao o INSERT NAO colidiria).

    Se dois telefones crus diferentes normalizarem para a MESMA chave, o
    arquivo e ambiguo (provavelmente um duplicado logico de fato no banco)
    — explode em vez de escolher um dos dois silenciosamente.
    """
    brutos = {}
    primeira_linha_bruta = ""
    vista_primeira_linha = False
    with open(caminho, encoding="utf-8") as fh:
        for bruta in fh:
            linha = bruta.rstrip("\n")
            if not vista_primeira_linha:
                primeira_linha_bruta = linha
                vista_primeira_linha = True
            if "\t" in linha:
                fone, nome = linha.split("\t", 1)
            elif "\\t" in linha:
                fone, nome = linha.split("\\t", 1)
            else:
                continue
            if fone.strip():
                brutos[fone.strip()] = nome.strip()
    # Fix round 2, Minor: um TSV cujo unico "\t" (real ou literal) esta na
    # linha de cabecalho ("telefone<TAB>nome") passa pela checagem "not
    # nomes" com uma unica entrada falsa {"telefone": "nome"} — mascarando
    # um arquivo sem dado nenhum. Um telefone de verdade e so digitos;
    # se a unica entrada nao for, trata como se nao tivesse achado nada.
    # (checagem feita sobre os telefones CRUS, antes de normalizar — mantem
    # o comportamento original destes dois guardrails.)
    quebrado = not brutos or (len(brutos) == 1 and not next(iter(brutos)).isdigit())
    if quebrado:
        raise ValueError(
            "nomes_crm: nenhuma linha com TAB encontrada em %s; primeira linha: %r"
            % (caminho, primeira_linha_bruta)
        )

    nomes = {}
    origem_por_normalizado = {}
    for fone_bruto, nome in brutos.items():
        normalizado = transform.normalizar_telefone(fone_bruto) or fone_bruto
        outro_bruto = origem_por_normalizado.get(normalizado)
        # Change 1: as 10 DUPLICATAS_EXCLUIDAS SAO exatamente esta colisao —
        # a mesma pessoa cadastrada com/sem prefixo 55. enriquecer() pula
        # essas linhas antes de consultar nomes_crm (nem lead, nem nota), ou
        # seja, o valor guardado aqui para essa chave nunca e lido por quem
        # importa de fato. Consultar a lista de exclusao aqui, na hora de
        # montar o mapa, e mais simples que adiar a checagem para "so
        # explode se o telefone for realmente usado" — exigiria passar a
        # lista de telefones do disparo para dentro deste parser, que hoje
        # so conhece o dump do CRM. Qualquer OUTRA ambiguidade (fora da
        # lista conhecida) continua explodindo, como antes.
        if (outro_bruto is not None and outro_bruto != fone_bruto
                and normalizado not in DUPLICATAS_EXCLUIDAS):
            raise ValueError(
                "nomes_crm: '%s' e '%s' normalizam para o mesmo telefone "
                "'%s' em %s — arquivo ambiguo (provavel duplicata logica no "
                "banco); resolva a duplicata antes de gerar o SQL."
                % (outro_bruto, fone_bruto, normalizado, caminho)
            )
        origem_por_normalizado[normalizado] = fone_bruto
        nomes[normalizado] = nome
    return nomes


def excluir_optouts_ja_marcados(optouts, ja_marcados):
    """Remove da lista os telefones que ja estao marcados opt_out=true no banco.

    Fix round 1, Finding 2 (CRITICAL): gerar_update_optout so atualiza quem
    tem "opt_out IS NOT TRUE", mas o rodape de verificacao espera
    len(optouts) linhas atualizadas. Se o arquivo de opt-outs incluir quem
    ja foi marcado por outro motivo, o UPDATE atualiza menos linhas do que
    o esperado e o RAISE EXCEPTION do rodape aborta a transacao inteira —
    inclusive os leads e notas que nada tinham a ver com opt-out. Filtrar
    aqui, antes de montar_arquivo, garante que len(optouts) reflita
    exatamente o que o UPDATE vai atualizar.

    Fix round 2, Finding 3 (CRITICAL): os dois lados sao normalizados via
    transform.normalizar_telefone antes de comparar. O CRM guarda telefones
    em 13, 11 e 10 digitos (ver docstring de normalizar_telefone); comparar
    strings brutas deixaria passar quem esta marcado num formato diferente
    do usado no arquivo de opt-outs — resssucitando o mesmo RAISE EXCEPTION
    / rollback total do Finding 2, so que via uma diferenca de formatacao.

    Devolve (lista_filtrada, telefones_excluidos_normalizados) — a segunda
    lista existe para quem chama poder auditar CADA telefone excluido
    (Fix round 2, Finding 4), em vez de confiar so na contagem.
    """
    marcados_normalizados = {transform.normalizar_telefone(f) for f in ja_marcados}
    filtrados, excluidos = [], []
    for item in optouts:
        fone_normalizado = transform.normalizar_telefone(item[0])
        if fone_normalizado in marcados_normalizados:
            excluidos.append(fone_normalizado)
        else:
            filtrados.append(item)
    return filtrados, excluidos


def diagnosticar_optouts_pulados(excluidos, nomes_crm):
    """Separa os telefones pulados em 'confirmados no CRM' e 'nao encontrados'.

    Fix round 2, Finding 4 (Important): a contagem de "pulados" nao pode se
    basear so no que --optouts-ja-marcados diz — um telefone errado/obsoleto
    naquele arquivo excluiria por engano uma pessoa que pediu opt-out de
    verdade, sem aviso nenhum (ela continuaria recebendo mensagens). Cruzar
    cada telefone excluido contra nomes_crm (todo lead que existe no CRM)
    aponta esse cenario: um telefone pulado que NAO esta no CRM significa
    que um dos dois arquivos de entrada esta errado.

    Devolve (confirmados_no_crm, nao_encontrados_no_crm), ambas listas de
    telefone normalizado.
    """
    confirmados = [fone for fone in excluidos if fone in nomes_crm]
    nao_encontrados = [fone for fone in excluidos if fone not in nomes_crm]
    return confirmados, nao_encontrados


def contar_duplicatas_puladas(linhas):
    """Conta quantas linhas do disparo caem em DUPLICATAS_EXCLUIDAS.

    Usado por main() para reportar a contagem separadamente das demais —
    enriquecer() ja filtra essas linhas antes de qualquer outro processamento
    (nem lead, nem nota), mas quem chama precisa saber quantas foram.
    """
    return sum(
        1 for linha in linhas
        if transform.normalizar_telefone(linha.get("whatsapp")) in DUPLICATAS_EXCLUIDAS
    )


def enriquecer(linhas, master, nomes_crm, donos):
    """Separa (novos, existentes) e completa cada dict.

    nomes_crm: telefone E.164 -> leads.name (vazio quando o CRM nao tem nome)
    donos:     telefones que ja tem assigned_to preenchido

    Change 1: linhas cujo telefone normalizado esta em DUPLICATAS_EXCLUIDAS
    sao puladas antes de qualquer outro processamento — nao entram em novos
    nem em existentes, nao recebem lead nem nota. Sao os 10 casos de
    duplicata logica no CRM (mesma pessoa cadastrada com/sem prefixo 55, com
    o historico dividido entre os dois registros) — sem merge previo dos
    dados, nao ha como escolher o registro certo.
    """
    novos, existentes = [], []
    for linha in linhas:
        dados = dict(linha)
        phone = transform.normalizar_telefone(dados.get("whatsapp"))
        if phone in DUPLICATAS_EXCLUIDAS:
            continue
        da_master = master.get((dados.get("id_bling") or "").strip(), {})
        for campo in CAMPOS_DA_MASTER:
            dados.setdefault(campo, "")
            if not dados.get(campo) and da_master.get(campo):
                dados[campo] = da_master[campo]
        dados["motivo_exclusao"] = MOTIVOS_EXCLUSAO.get(phone, "")
        nome_crm = nomes_crm.get(phone) or None
        entrada = (dados, nome_crm, phone in donos)
        (existentes if phone in nomes_crm else novos).append(entrada)
    return novos, existentes


def main(argv=None):
    parser = argparse.ArgumentParser(description="Gera o SQL da preparacao de reativacao.")
    parser.add_argument("--disparo", required=True, help="CSV da lista de disparo")
    parser.add_argument("--master", required=True, help="CSV master de leads")
    parser.add_argument("--nomes-crm", required=True,
                        help="TSV 'telefone<TAB>nome' dos leads que ja existem no CRM")
    parser.add_argument("--donos", default="",
                        help="arquivo com um telefone por linha que ja tem assigned_to")
    parser.add_argument("--optouts", required=True,
                        help="JSON telefone -> {data, texto} contendo APENAS opt-outs que "
                             "ainda NAO estao marcados (opt_out=false) no banco — a contagem "
                             "deste arquivo e usada como assercao exata no SQL gerado. "
                             "Quem ja esta marcado deve ir em --optouts-ja-marcados.")
    parser.add_argument("--optouts-ja-marcados", default="",
                        help="arquivo com um telefone por linha ja marcado opt_out=true no "
                             "banco; qualquer telefone aqui presente e removido da lista de "
                             "--optouts para a contagem de verificacao do SQL nao divergir")
    parser.add_argument("--esperado-novos", type=int, default=None,
                        help="se informado, aborta (sem escrever SQL) se a contagem de leads "
                             "novos nao bater exatamente com este numero")
    parser.add_argument("--esperado-existentes", type=int, default=None,
                        help="se informado, aborta (sem escrever SQL) se a contagem de leads "
                             "existentes nao bater exatamente com este numero")
    parser.add_argument("--saida", required=True, help="diretorio de saida")
    args = parser.parse_args(argv)

    try:
        nomes_crm = carregar_nomes_crm(args.nomes_crm)
    except ValueError as erro:
        print("ERRO: %s" % erro, file=sys.stderr)
        return 1

    # Fix round 3 (C2, CRITICAL): mesma normalizacao de carregar_nomes_crm —
    # o banco guarda telefone cru (10/11/12/13 digitos) e enriquecer()
    # consulta "donos" com o telefone JA normalizado. Sem isso, um lead com
    # dono em formato curto (ex.: 11 digitos) seria tratado como "sem dono"
    # e teria assigned_to sobrescrito para o Joao.
    donos = set()
    if args.donos and os.path.exists(args.donos):
        with open(args.donos, encoding="utf-8") as fh:
            donos = {transform.normalizar_telefone(l.strip()) or l.strip()
                     for l in fh if l.strip()}

    with open(args.optouts, encoding="utf-8") as fh:
        optout_raw = json.load(fh)
    optouts_brutos = [(fone, dado.get("data", ""), dado.get("texto", ""))
                      for fone, dado in optout_raw.items()]

    optouts_ja_marcados = set()
    if args.optouts_ja_marcados and os.path.exists(args.optouts_ja_marcados):
        with open(args.optouts_ja_marcados, encoding="utf-8") as fh:
            optouts_ja_marcados = {l.strip() for l in fh if l.strip()}
    optouts, optouts_excluidos = excluir_optouts_ja_marcados(optouts_brutos, optouts_ja_marcados)
    optouts_confirmados, optouts_nao_encontrados = diagnosticar_optouts_pulados(
        optouts_excluidos, nomes_crm)

    linhas = carregar_disparo(args.disparo)
    master = carregar_master(args.master)
    duplicatas_puladas = contar_duplicatas_puladas(linhas)
    novos, existentes = enriquecer(linhas, master, nomes_crm, donos)

    # Fix round 1, Finding 1: um humano comparando os numeros impressos so
    # pegaria uma divergencia se soubesse os numeros esperados de cor. Com
    # --esperado-novos/--esperado-existentes, a ferramenta se recusa a
    # escrever qualquer SQL quando a contagem nao bate.
    erros_contagem = []
    if args.esperado_novos is not None and len(novos) != args.esperado_novos:
        erros_contagem.append(
            "novos: esperado %d, obtido %d" % (args.esperado_novos, len(novos)))
    if args.esperado_existentes is not None and len(existentes) != args.esperado_existentes:
        erros_contagem.append(
            "existentes: esperado %d, obtido %d" % (args.esperado_existentes, len(existentes)))
    if erros_contagem:
        print("ERRO: contagem nao bate com o esperado -> %s" % "; ".join(erros_contagem),
              file=sys.stderr)
        return 1

    os.makedirs(args.saida, exist_ok=True)
    caminho_sql = os.path.join(args.saida, "preparar.sql")
    caminho_rb = os.path.join(args.saida, "rollback.sql")
    with open(caminho_sql, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(montar_arquivo(novos, existentes, optouts, NORMALIZACOES))
    with open(caminho_rb, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(montar_rollback())

    print("leads novos:      %d" % len(novos))
    print("leads existentes: %d" % len(existentes))
    print("notas:            %d" % (len(novos) + len(existentes)))
    print("opt-outs:         %d" % len(optouts))
    # Fix round 2, Finding 4: nao basta reportar "N pulados" no say-so do
    # arquivo --optouts-ja-marcados. Separar confirmados/nao-encontrados no
    # CRM e mostrar os telefones ofensivos deixa visivel quando um dos dois
    # arquivos de entrada esta errado, em vez de dropar um opt-out real
    # (pessoa continuaria recebendo mensagem) sem aviso nenhum.
    print("  pulados (confirmados no CRM):     %d" % len(optouts_confirmados))
    print("  pulados (NAO encontrados no CRM): %d" % len(optouts_nao_encontrados))
    if optouts_nao_encontrados:
        print("  ATENCAO — telefones pulados que NAO estao no CRM "
              "(revisar --optouts e --optouts-ja-marcados):")
        for fone in optouts_nao_encontrados:
            print("    - %s" % fone)
    print("exclusoes:        %d" % sum(
        1 for d, _, _ in list(novos) + list(existentes) if d["motivo_exclusao"]))
    # Change 1: contagem separada das demais — estas linhas nem entram em
    # novos/existentes, nao recebem lead nem nota (ver contar_duplicatas_puladas
    # e enriquecer).
    print("duplicatas puladas (CRM): %d" % duplicatas_puladas)
    print("gerado: %s" % caminho_sql)
    print("gerado: %s" % caminho_rb)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
