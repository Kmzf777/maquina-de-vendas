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
