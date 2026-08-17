# scripts/reativacao/lote_completo.py
"""Gera o SQL do lote completo do Bling. Nao executa nada.

O artefato revisavel e o proprio .sql, aplicado por um humano via psql depois
do pg_dump. Ver docs/superpowers/plans/2026-08-14-reativacao-bling-lote-completo.md

Difere de generate_sql.py (lote de 10/08) em tres pontos: usa
transform.normalizar_telefone_canonico (injeta o 9o digito), cria funil +
etapas + deals, e nao tem curadoria manual de saudacao nem score de ICP.
"""
import argparse
import csv
import json
import os
import re
import sys
from collections import namedtuple

import transform

LOTE = "reativacao_bling_2026-08-14"
ORIGEM = "reativacao_bling"
# Precisa ser DIFERENTE do AUTOR_NOTA de generate_sql.py (lote de 10/08), que e
# "Sistema — Reativação Bling". Com a string repetida, o bloco de verificacao
# contaria as notas dos dois lotes e o DELETE do rollback apagaria as do outro.
AUTOR_NOTA = "Sistema — Reativação Bling 08/26"
PREFIXO_BRIEFING = "REATIVAÇÃO BLING 14/08/2026 — lote reativacao_bling_2026-08-14"

# UUIDs hardcoded: deixam os INSERTs idempotentes e dao ao rollback um alvo
# preciso. O de TAG_DEBITO_VENCIDO e referenciado pelo frontend
# (frontend/src/lib/constants.ts) — mudar aqui exige mudar la.
PIPELINE_ID = "b2f9c31d-8a47-4e26-95c0-3d7a1f6e8b09"
PIPELINE_NOME = "Reativação Bling"
# Dono do funil = Joao (joao@cafecanastra.com), unico vendedor que trabalha esta
# carteira. Sem dono, nenhum vendedor enxerga o funil nem os cards — ver a
# docstring de gerar_pipeline_e_etapas. Para abrir a todos os vendedores em vez
# de um so, o caminho e is_universal = true, nao owner NULL.
PIPELINE_OWNER_ID = "1c3c78ed-ef47-4dca-9a63-2052f28e8fd6"

# (key, label, cor, uuid) — a ordem da tupla e a ordem no Kanban.
ETAPAS = (
    ("ativo_0_3m",         "Ativo (0-3m)",        "#5aad65", "a1c4e7b2-5d38-4f61-9a02-7e5b3c8d1f40"),
    ("inativo_3_6m",       "Inativo 3-6m",        "#d4b84a", "b2d5f8c3-6e49-4a72-8b13-6f4c2d9e0a51"),
    ("inativo_6_12m",      "Inativo 6-12m",       "#d4a04a", "c3e6a9d4-7f50-4b83-9c24-5a3d1e8f2b62"),
    ("inativo_12_24m",     "Inativo 12-24m",      "#e07a7a", "d4f7b0e5-8a61-4c94-8d35-4b2e0f7a3c73"),
    ("inativo_24_36m",     "Inativo 24-36m",      "#c46a6a", "e5a8c1f6-9b72-4d05-9e46-3c1f0a6b4d84"),
    ("inativo_36m_mais",   "Inativo 36m+",        "#9ca3af", "f6b9d2a7-0c83-4e16-8f57-2d0a1b5c6e95"),
    ("pedido_sem_faturar", "Pedido sem faturar",  "#9b7abf", "07cae3b8-1d94-4f27-9068-1e0b2c4d7fa6"),
    ("lead_sem_compra",    "Nunca comprou",       "#b0aca6", "18dbf4c9-2ea5-4038-8179-0f1c3d5e8ab7"),
)

ETAPA_POR_SEGMENTO = {
    "ativo_0_3m": "ativo_0_3m",
    "inativo_3_6m": "inativo_3_6m",
    "inativo_6_12m": "inativo_6_12m",
    "inativo_12_24m": "inativo_12_24m",
    "inativo_24_36m": "inativo_24_36m",
    "inativo_36m+": "inativo_36m_mais",
    "pedido_sem_faturar": "pedido_sem_faturar",
    "lead_sem_compra": "lead_sem_compra",
}

TAG_LOTE_ID = "7c4e2a19-3f68-4b02-9d5a-1e8f6c0b3d47"
TAG_LOTE_NOME = "Reativação Bling 08/26"
TAG_DEBITO_ID = "3d1b8e6c-7a24-4f95-b8d1-5c0e9a47f210"
TAG_DEBITO_NOME = "Débito vencido"
TAG_B2B_ID = "2249642b-e4f2-420e-8482-d07b325a28c8"  # ja existe no banco
TAG_ECOMMERCE_ID = "5e2f7a83-4b91-4c60-a8d2-9f3e1b0c7d54"
TAG_SEM_VENDEDOR_ID = "6f3a8b94-5c02-4d71-b9e3-0a4f2c1d8e65"

# (uuid, nome, cor) das tags que este lote cria. B2B fica fora: ja existe.
TAGS_A_CRIAR = (
    (TAG_LOTE_ID, TAG_LOTE_NOME, "#7C3AED"),
    (TAG_DEBITO_ID, TAG_DEBITO_NOME, "#DC2626"),
    (TAG_ECOMMERCE_ID, "E-commerce", "#0D9488"),
    (TAG_SEM_VENDEDOR_ID, "Sem vendedor", "#6B7280"),
)

PLATAFORMAS_ECOMMERCE = ("TRAY TECNOLOGIA EM ECOMMERCE LTDA", "WooCommerce", "Licitação")

# Guardrail: o SQL gerado nunca pode tocar o disparo.
TABELAS_PROIBIDAS = ("broadcasts", "broadcast_leads")

Coorte = namedtuple(
    "Coorte", "novos ja_no_crm sem_telefone duplicados_no_csv nao_parseavel")


def sql_literal(valor):
    """Escapa para literal SQL; vazio/None viram NULL."""
    if valor is None:
        return "NULL"
    texto = str(valor).strip()
    if not texto:
        return "NULL"
    return "'" + texto.replace("'", "''") + "'"


def etapa_de(linha):
    """Key da etapa a partir do segmento_reativacao do Bling."""
    segmento = (linha.get("segmento_reativacao") or "").strip()
    if segmento not in ETAPA_POR_SEGMENTO:
        raise ValueError(
            "segmento desconhecido no CSV: %r — o funil tem 8 etapas fixas e um "
            "segmento novo faria o lead sumir silenciosamente" % segmento
        )
    return ETAPA_POR_SEGMENTO[segmento]


def perfil_comercial(linha):
    """B2B | E-commerce | Sem vendedor — vira tag.

    IDs numericos no campo vendedor sao vendedores humanos cujo nome nao foi
    resolvido na extracao do Bling, entao contam como B2B.
    """
    vendedor = (linha.get("vendedor") or "").strip()
    if vendedor in PLATAFORMAS_ECOMMERCE:
        return "E-commerce"
    if not vendedor:
        return "Sem vendedor"
    return "B2B"


def telefone_da_linha(linha):
    """Primeiro telefone utilizavel de uma linha, na forma canonica.

    O piso de 10 digitos descarta dado truncado no Bling (ex.: "+33 6 68 60 37",
    que perdeu os dois ultimos digitos) e deixa a busca cair na proxima coluna,
    onde costuma estar o numero completo. Sem ele, o lead entraria com um
    telefone que nao disca.
    """
    for campo in ("whatsapp", "celular", "telefone"):
        fone = transform.normalizar_telefone_canonico(linha.get(campo))
        if len(fone) >= 10:
            return fone
    return ""


def selecionar_faltantes(linhas, telefones_crm):
    """Divide o CSV em: a criar, ja no CRM, sem telefone, duplicados.

    `telefones_crm` deve chegar JA normalizado pela forma canonica — quem
    carrega o arquivo do banco (carregar_telefones_crm) faz isso.
    """
    novos, vistos = [], set()
    ja_no_crm = sem_telefone = duplicados = nao_parseavel = 0
    for linha in linhas:
        fone = telefone_da_linha(linha)
        if not fone:
            sem_telefone += 1
            # Distingue "cadastro sem telefone" de "tinha telefone e nos
            # descartamos" — ex.: dois numeros no mesmo campo
            # ("(19) 3211-6200 / (19) 3211-6333") ou numero truncado no Bling.
            if any(re.search(r"\d", linha.get(campo) or "")
                   for campo in ("whatsapp", "celular", "telefone")):
                nao_parseavel += 1
            continue
        if fone in telefones_crm:
            ja_no_crm += 1
            continue
        if fone in vistos:
            duplicados += 1
            continue
        vistos.add(fone)
        enriquecida = dict(linha)
        enriquecida["_phone"] = fone
        novos.append(enriquecida)
    return Coorte(novos, ja_no_crm, sem_telefone, duplicados, nao_parseavel)


def metadata_do_lead(linha):
    """Chaves de rastreio + os numeros do debito que o banner da UI exibe.

    origem+lote juntas sao o que o rollback usa; criado_por_lote marca quem
    este lote CRIOU (distinto de quem ele apenas tocou).
    """
    dados = {
        "origem": ORIGEM,
        "lote": LOTE,
        "criado_por_lote": LOTE,
        "id_bling": (linha.get("id_bling") or "").strip(),
        "segmento": etapa_de(linha),
        "vendedor_anterior": (linha.get("vendedor") or "").strip(),
        "total_gasto": transform.parse_numero(linha.get("total_gasto")),
        "ultima_compra": (linha.get("ultima_compra") or "").strip(),
        "whatsapp_tipo": (linha.get("whatsapp_tipo") or "").strip(),
        "phone_raw": (linha.get("whatsapp") or "").strip(),
    }
    if transform.parse_numero(linha.get("valor_vencido")) > 0:
        dados["valor_vencido"] = transform.parse_numero(linha.get("valor_vencido"))
        dados["titulos_vencidos"] = transform.parse_inteiro(linha.get("titulos_vencidos"))
        dados["dias_atraso_max"] = transform.parse_inteiro(linha.get("dias_atraso_max"))
    return dados


def nome_do_lead(linha):
    """leads.name e o que o cliente le como {{1}} no template do WhatsApp.

    Este lote nao tem coluna 'saudacao' curada a mao (o de 10/08 tinha, para
    276 linhas); escolher_saudacao limpa codigo/CNPJ do inicio e sufixos
    empresariais do nome legal do Bling.
    """
    return transform.escolher_saudacao(None, linha.get("nome"))


def gerar_insert_lead(linha):
    """INSERT idempotente de um lead novo.

    ai_enabled entra como literal booleano, nunca via sql_literal (que
    renderizaria a STRING 'False'): leads.ai_enabled e NOT NULL DEFAULT TRUE, e
    o motor de automacao seleciona por "ai_enabled = true AND stage = ...".

    assigned_to fica de fora (decisao D3): sem dono ate a campanha ser montada.
    """
    metadata = json.dumps(metadata_do_lead(linha), ensure_ascii=False, sort_keys=True)
    return (
        "INSERT INTO leads (phone, name, company, razao_social, nome_fantasia, "
        "cnpj, email, endereco, telefone_comercial, stage, status, channel, "
        "ai_enabled, opt_out, metadata) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, "
        "%s, 'pending', 'imported', 'manual', false, false, %s::jsonb) "
        "ON CONFLICT (phone) DO NOTHING;" % (
            sql_literal(linha["_phone"]),
            sql_literal(nome_do_lead(linha)),
            sql_literal(linha.get("nome")),
            sql_literal(linha.get("razao_social") or linha.get("nome")),
            # A coluna do CSV do Bling se chama "fantasia"; "nome_fantasia" e o
            # nome da coluna no CRM. Ler pelo nome do CRM devolvia NULL sempre.
            sql_literal(linha.get("fantasia")),
            sql_literal(re.sub(r"\D", "", linha.get("cpf_cnpj") or "")),
            sql_literal(linha.get("email")),
            sql_literal(linha.get("endereco_entrega") or linha.get("logradouro")),
            sql_literal(linha.get("telefone")),
            sql_literal(metadata),
        )
    )


def dados_do_briefing(linha):
    """Adapta os nomes de coluna do CSV cru para o que montar_briefing espera."""
    dados = dict(linha)
    dados["produto_para_citar"] = (linha.get("produto_top1") or "").strip()
    return dados


def gerar_insert_nota(linha):
    """Nota de briefing, idempotente: nao duplica se ja houver nota deste autor."""
    conteudo = transform.montar_briefing(dados_do_briefing(linha), prefixo=PREFIXO_BRIEFING)
    return (
        "INSERT INTO lead_notes (lead_id, author, content)\n"
        "SELECT l.id, %s, %s FROM leads l WHERE l.phone = %s\n"
        "  AND NOT EXISTS (SELECT 1 FROM lead_notes n WHERE n.lead_id = l.id "
        "AND n.author = %s);" % (
            sql_literal(AUTOR_NOTA), sql_literal(conteudo),
            sql_literal(linha["_phone"]), sql_literal(AUTOR_NOTA))
    )


UUID_POR_ETAPA = {key: uuid_ for key, _label, _cor, uuid_ in ETAPAS}


def gerar_insert_deal(linha):
    """Um deal por lead, na etapa do seu segmento.

    Titulo segue a convencao de frontend/src/lib/import-deals.ts:33 —
    "<nome> - <funil>". Idempotente: nao cria segundo deal no mesmo funil.
    """
    titulo = "%s - %s" % (nome_do_lead(linha), PIPELINE_NOME)
    return (
        "INSERT INTO deals (lead_id, title, value, stage, pipeline_id, stage_id)\n"
        "SELECT l.id, %s, 0, 'novo', %s, %s FROM leads l WHERE l.phone = %s\n"
        "  AND NOT EXISTS (SELECT 1 FROM deals d WHERE d.lead_id = l.id "
        "AND d.pipeline_id = %s);" % (
            sql_literal(titulo), sql_literal(PIPELINE_ID),
            sql_literal(UUID_POR_ETAPA[etapa_de(linha)]),
            sql_literal(linha["_phone"]), sql_literal(PIPELINE_ID))
    )


def _vinculo_tag(tag_id, telefones):
    """Associa a tag a um conjunto de telefones, sem duplicar vinculo.

    lead_tags tem PRIMARY KEY (lead_id, tag_id) — supabase/migrations/
    002_crm_enrichment.sql:66 — entao ON CONFLICT DO NOTHING serviria igual.
    O NOT EXISTS faz o mesmo sem depender do nome da constraint.
    """
    if not telefones:
        return ""
    lista = ", ".join(sql_literal(f) for f in sorted(telefones))
    return (
        "INSERT INTO lead_tags (lead_id, tag_id)\n"
        "SELECT l.id, %s FROM leads l WHERE l.phone IN (%s)\n"
        "  AND NOT EXISTS (SELECT 1 FROM lead_tags t WHERE t.lead_id = l.id "
        "AND t.tag_id = %s);\n" % (sql_literal(tag_id), lista, sql_literal(tag_id))
    )


def gerar_tags(coorte):
    """Cria as tags do lote e associa cada uma ao seu subconjunto.

    B2B ja existe no banco (2249642b-...), entao so ganha vinculo.
    """
    partes = ["-- Tags do lote"]
    for tag_id, nome, cor in TAGS_A_CRIAR:
        partes.append(
            "INSERT INTO tags (id, name, color) VALUES (%s, %s, %s) "
            "ON CONFLICT (id) DO NOTHING;" % (
                sql_literal(tag_id), sql_literal(nome), sql_literal(cor))
        )
    partes.append("")

    por_perfil = {"B2B": set(), "E-commerce": set(), "Sem vendedor": set()}
    todos, com_debito = set(), set()
    for linha in coorte:
        fone = linha["_phone"]
        todos.add(fone)
        por_perfil[perfil_comercial(linha)].add(fone)
        if transform.parse_numero(linha.get("valor_vencido")) > 0:
            com_debito.add(fone)

    partes.append(_vinculo_tag(TAG_LOTE_ID, todos))
    partes.append(_vinculo_tag(TAG_B2B_ID, por_perfil["B2B"]))
    partes.append(_vinculo_tag(TAG_ECOMMERCE_ID, por_perfil["E-commerce"]))
    partes.append(_vinculo_tag(TAG_SEM_VENDEDOR_ID, por_perfil["Sem vendedor"]))
    partes.append(_vinculo_tag(TAG_DEBITO_ID, com_debito))
    return "\n".join(p for p in partes if p is not None)


def gerar_pipeline_e_etapas():
    """Funil + 8 etapas, idempotentes pelo UUID fixo.

    O funil PRECISA de dono. A regra de visibilidade (pipeline-access.ts e a
    policy deals_select) e "admin OU owner_user_id = auth.uid() OU
    is_universal": com owner NULL e is_universal false, o funil e os 1.208 cards
    ficam invisiveis para TODO vendedor, so admin enxerga. Foi o que aconteceu
    na primeira aplicacao — o Joao nao via o funil.

    Nao confundir com os funis "Valeria - ..." e "Arthur - Exportacao", que
    tambem estao com owner NULL: eles sao administrativos de fato (o Arthur e
    admin), nao um contraexemplo de que NULL funciona para vendedor.
    """
    partes = [
        "-- Funil do lote e suas etapas",
        "INSERT INTO pipelines (id, name, order_index, owner_user_id, is_universal)",
        "VALUES (%s, %s, 99, %s, false)" % (
            sql_literal(PIPELINE_ID), sql_literal(PIPELINE_NOME),
            sql_literal(PIPELINE_OWNER_ID)),
        "ON CONFLICT (id) DO NOTHING;",
        "",
    ]
    for indice, (key, label, cor, uuid_) in enumerate(ETAPAS):
        partes.append(
            "INSERT INTO pipeline_stages (id, pipeline_id, label, key, dot_color, "
            "order_index, is_protected) VALUES (%s, %s, %s, %s, %s, %d, false) "
            "ON CONFLICT (id) DO NOTHING;" % (
                sql_literal(uuid_), sql_literal(PIPELINE_ID), sql_literal(label),
                sql_literal(key), sql_literal(cor), indice)
        )
    partes.append("")
    return "\n".join(partes)


def _bloco_verificacao(rotulo, expressao_where, esperado):
    """RAISE EXCEPTION aborta a transacao inteira e desfaz tudo que veio antes."""
    return (
        "\\echo '--- %s (esperado %d) ---'\n"
        "DO $$\nDECLARE encontrado integer;\nBEGIN\n"
        "  SELECT count(*) INTO encontrado FROM %s;\n"
        "  IF encontrado <> %d THEN\n"
        "    RAISE EXCEPTION 'esperado %d em %s, encontrado %%', encontrado;\n"
        "  END IF;\nEND $$;\n" % (
            rotulo, esperado, expressao_where, esperado, esperado, rotulo)
    )


def montar_arquivo(coorte):
    """preparar.sql completo, em transacao unica."""
    total = len(coorte)
    partes = [
        "\\set ON_ERROR_STOP on",
        "-- Lote %s — %d leads. NAO EDITAR A MAO: regenerar com lote_completo.py" % (LOTE, total),
        "BEGIN;",
        "",
        gerar_pipeline_e_etapas(),
        "-- Leads",
    ]
    partes.extend(gerar_insert_lead(l) for l in coorte)
    partes.append("\n-- Notas de briefing")
    partes.extend(gerar_insert_nota(l) for l in coorte)
    partes.append("\n-- Deals")
    partes.extend(gerar_insert_deal(l) for l in coorte)
    partes.append("")
    partes.append(gerar_tags(coorte))
    partes.append("-- Verificacao (aborta a transacao inteira se nao bater)")
    partes.append(_bloco_verificacao(
        "leads do lote",
        "leads WHERE metadata->>'origem' = '%s' AND metadata->>'lote' = '%s'" % (ORIGEM, LOTE),
        total))
    partes.append(_bloco_verificacao(
        "notas do lote", "lead_notes WHERE author = '%s'" % AUTOR_NOTA, total))
    partes.append(_bloco_verificacao(
        "deals do funil", "deals WHERE pipeline_id = '%s'" % PIPELINE_ID, total))
    partes.append(_bloco_verificacao(
        "etapas do funil", "pipeline_stages WHERE pipeline_id = '%s'" % PIPELINE_ID,
        len(ETAPAS)))
    partes.append("COMMIT;")
    return "\n".join(partes)


def montar_rollback():
    """Desfaz exatamente o que este lote criou, na ordem de dependencia."""
    tags_do_lote = [TAG_LOTE_ID, TAG_DEBITO_ID, TAG_ECOMMERCE_ID,
                    TAG_SEM_VENDEDOR_ID, TAG_B2B_ID]
    lista_tags = ", ".join(sql_literal(t) for t in tags_do_lote)
    return "\n".join([
        "\\set ON_ERROR_STOP on",
        "-- Rollback do lote %s" % LOTE,
        "BEGIN;",
        "",
        "-- 1. Vinculos de tag dos leads que este lote criou (as cinco tags).",
        "--    As tags NAO sao apagadas de proposito: o DELETE cascatearia em",
        "--    lead_tags e levaria vinculos criados a mao depois da importacao. E o",
        "--    UUID da tag \"Debito vencido\" esta hardcoded em",
        "--    frontend/src/lib/constants.ts — recria-la pela UI geraria outro id e o",
        "--    aviso do modal de disparo morreria em silencio.",
        "DELETE FROM lead_tags WHERE tag_id IN (%s) AND lead_id IN (" % lista_tags,
        "  SELECT id FROM leads WHERE metadata->>'criado_por_lote' = %s);" % sql_literal(LOTE),
        "",
        "-- 2. Deals do funil, depois as etapas, depois o funil.",
        "DELETE FROM deals WHERE pipeline_id = %s;" % sql_literal(PIPELINE_ID),
        "DELETE FROM pipeline_stages WHERE pipeline_id = %s;" % sql_literal(PIPELINE_ID),
        "DELETE FROM pipelines WHERE id = %s;" % sql_literal(PIPELINE_ID),
        "",
        "-- Nao ha DELETE de lead_notes de proposito: a FK tem ON DELETE CASCADE e este",
        "-- lote so cria leads novos, entao toda nota deste autor pertence a um lead",
        "-- dele. Apagar por autor aqui tiraria o briefing tambem dos leads que as",
        "-- guardas do passo 3 preservam — exatamente os que alguem ja esta trabalhando.",
        "",
        "-- 3. Os leads que este lote CRIOU (nunca os pre-existentes), pulando os que",
        "--    ja foram trabalhados. sales, messages e conversion_events cascateiam em",
        "--    silencio (venda registrada sumiria sem aviso); token_usage e",
        "--    follow_up_jobs referenciam leads SEM ON DELETE e abortariam o rollback",
        "--    inteiro. A ultima guarda pega nota escrita a mao por vendedor.",
        "DELETE FROM leads l WHERE l.metadata->>'criado_por_lote' = %s" % sql_literal(LOTE),
        "  AND NOT EXISTS (SELECT 1 FROM sales s WHERE s.lead_id = l.id)",
        "  AND NOT EXISTS (SELECT 1 FROM messages m WHERE m.lead_id = l.id)",
        "  AND NOT EXISTS (SELECT 1 FROM conversion_events e WHERE e.lead_id = l.id)",
        "  AND NOT EXISTS (SELECT 1 FROM token_usage t WHERE t.lead_id = l.id)",
        "  AND NOT EXISTS (SELECT 1 FROM follow_up_jobs f WHERE f.lead_id = l.id)",
        "  AND NOT EXISTS (SELECT 1 FROM lead_notes n WHERE n.lead_id = l.id",
        "                    AND n.author <> %s);" % sql_literal(AUTOR_NOTA),
        "",
        "\\echo '--- leads do lote preservados pelas guardas (esperado: 0) ---'",
        "\\echo 'Diferente de zero significa: esses leads ja foram trabalhados (venda,'",
        "\\echo 'mensagem, conversao, custo de IA, follow-up agendado ou nota escrita a'",
        "\\echo 'mao) e NAO foram apagados. Decida a mao o que fazer com cada um.'",
        "SELECT count(*) AS leads_preservados FROM leads",
        "  WHERE metadata->>'criado_por_lote' = %s;" % sql_literal(LOTE),
        "COMMIT;",
    ])


def carregar_csv(caminho):
    with open(caminho, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh, delimiter=";"))


def carregar_telefones_crm(caminho):
    """Lê o dump de telefones do CRM (uma coluna por linha) já normalizado.

    Aborta em arquivo vazio: tratar "CRM vazio" como estado normal faria o
    script criar 1.218 leads duplicados sobre uma base que ja os tem.
    """
    with open(caminho, encoding="utf-8") as fh:
        fones = {transform.normalizar_telefone_canonico(l) for l in fh if l.strip()}
    fones.discard("")
    if not fones:
        raise ValueError(
            "telefones_crm vazio: %s — o CRM tem 2.339 leads, um arquivo vazio "
            "significa extracao quebrada, nao base vazia" % caminho
        )
    return fones


def main(argv=None):
    parser = argparse.ArgumentParser(description="Gera o SQL do lote completo do Bling.")
    parser.add_argument("--csv", required=True, help="CSV completo do Bling")
    parser.add_argument("--telefones-crm", required=True,
                        help="uma coluna: todos os telefones que ja existem em leads")
    parser.add_argument("--esperado-novos", type=int, required=True,
                        help="trava: aborta se a contagem calculada nao bater")
    parser.add_argument("--saida", required=True)
    args = parser.parse_args(argv)

    linhas = carregar_csv(args.csv)
    telefones_crm = carregar_telefones_crm(args.telefones_crm)
    coorte = selecionar_faltantes(linhas, telefones_crm)

    print("linhas no CSV:        %d" % len(linhas))
    print("ja no CRM:            %d" % coorte.ja_no_crm)
    print("sem telefone:         %d" % coorte.sem_telefone)
    print("  destes, com texto no campo mas nao parseavel: %d" % coorte.nao_parseavel)
    print("duplicados no CSV:    %d" % coorte.duplicados_no_csv)
    print("leads a criar:        %d" % len(coorte.novos))

    if len(coorte.novos) != args.esperado_novos:
        print("ERRO: contagem nao bate com o esperado -> %d != %d" % (
            len(coorte.novos), args.esperado_novos), file=sys.stderr)
        return 1

    preparar = montar_arquivo(coorte.novos)
    for tabela in TABELAS_PROIBIDAS:
        if tabela in preparar:
            print("ERRO: SQL referencia tabela proibida %r" % tabela, file=sys.stderr)
            return 1

    os.makedirs(args.saida, exist_ok=True)
    with open(os.path.join(args.saida, "preparar.sql"), "w", encoding="utf-8") as fh:
        fh.write(preparar)
    with open(os.path.join(args.saida, "rollback.sql"), "w", encoding="utf-8") as fh:
        fh.write(montar_rollback())
    print("gerado: %s" % os.path.join(args.saida, "preparar.sql"))
    print("gerado: %s" % os.path.join(args.saida, "rollback.sql"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
