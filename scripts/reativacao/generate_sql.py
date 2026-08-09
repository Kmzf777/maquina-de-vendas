# scripts/reativacao/generate_sql.py
"""Gera o SQL da preparacao de reativacao. Nao executa nada.

O artefato revisavel e o proprio arquivo .sql: ele e inspecionado antes de rodar
via psql, dentro de uma transacao, depois do pg_dump. Ver
docs/superpowers/plans/2026-08-08-reativacao-crm-preparacao.md
"""
import json

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
    """INSERT idempotente de um lead novo."""
    phone = transform.normalizar_telefone(dados.get("whatsapp"))
    nome = transform.escolher_saudacao(nome_crm, dados.get("nome"))
    metadata = json.dumps(_metadata_json(dados), ensure_ascii=False)
    return (
        "INSERT INTO leads (phone, name, company, stage, status, channel, "
        "assigned_to, cnpj, razao_social, nome_fantasia, email, endereco, metadata)\n"
        "VALUES (%s, %s, %s, 'pending', 'imported', %s, %s::uuid, %s, %s, %s, %s, %s, %s::jsonb)\n"
        "ON CONFLICT (phone) DO NOTHING;" % (
            sql_literal(phone),
            sql_literal(nome),
            sql_literal(dados.get("razao_social") or dados.get("nome")),
            sql_literal(CANAL_JOAO),
            sql_literal(JOAO_UUID),
            sql_literal(dados.get("cpf_cnpj")),
            sql_literal(dados.get("razao_social")),
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
        "razao_social = COALESCE(NULLIF(razao_social, ''), %s)" % sql_literal(dados.get("razao_social")),
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
    """Marca opt_out e registra a evidencia no metadata."""
    phone = transform.normalizar_telefone(telefone)
    evidencia = json.dumps(
        {"optout_quando": quando, "optout_disse": (disse or "")[:200], "optout_fonte": "mensagem_do_cliente"},
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
    """Corrige um phone para E.164, sem colidir com registro existente (D9)."""
    return (
        "UPDATE leads SET phone = %s\n"
        "WHERE phone = %s\n"
        "  AND NOT EXISTS (SELECT 1 FROM leads outro WHERE outro.phone = %s);" % (
            sql_literal(novo), sql_literal(antigo), sql_literal(novo))
    )


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
""" % LOTE

RODAPE = """
-- ── Verificacao (dentro da transacao, antes do COMMIT) ─────────────────────
\\echo '--- leads do lote (esperado: 276) ---'
SELECT count(*) AS leads_do_lote FROM leads WHERE metadata->>'lote' = '%(lote)s';

\\echo '--- notas do lote (esperado: 276) ---'
SELECT count(*) AS notas_do_lote FROM lead_notes WHERE content LIKE '%%%(lote)s%%';

\\echo '--- opt-outs marcados (esperado: 51) ---'
SELECT count(*) AS optouts_do_lote FROM leads
WHERE opt_out AND metadata->>'optout_fonte' = 'mensagem_do_cliente';

COMMIT;
""" % {"lote": LOTE}


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

    partes.append(RODAPE)
    return "\n\n".join(partes)


def montar_rollback():
    """Desfaz exatamente este lote.

    So remove lead que este lote criou: tem metadata.lote e nenhuma mensagem
    (um lead pre-existente que recebeu merge no metadata tem historico de
    conversa, e nao pode ser apagado).
    """
    return """-- Rollback do lote %(lote)s
-- Remove SO o que este lote criou. Leads pre-existentes que receberam merge de
-- metadata ou nota permanecem — apenas a nota e o metadata do lote saem.
\\set ON_ERROR_STOP on
BEGIN;

DELETE FROM lead_notes WHERE content LIKE '%%%(lote)s%%';

UPDATE leads SET opt_out = false
WHERE opt_out AND metadata->>'optout_fonte' = 'mensagem_do_cliente';

DELETE FROM leads l
WHERE l.metadata->>'lote' = '%(lote)s'
  AND NOT EXISTS (SELECT 1 FROM messages m WHERE m.lead_id = l.id);

UPDATE leads SET metadata = metadata - 'lote' - 'origem' - 'id_bling' - 'icp_score'
WHERE metadata->>'lote' = '%(lote)s';

\\echo '--- deve retornar 0 ---'
SELECT count(*) AS restantes FROM lead_notes WHERE content LIKE '%%%(lote)s%%';

COMMIT;
""" % {"lote": LOTE}
