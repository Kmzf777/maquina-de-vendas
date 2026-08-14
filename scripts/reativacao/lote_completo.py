# scripts/reativacao/lote_completo.py
"""Gera o SQL do lote completo do Bling. Nao executa nada.

O artefato revisavel e o proprio .sql, aplicado por um humano via psql depois
do pg_dump. Ver docs/superpowers/plans/2026-08-14-reativacao-bling-lote-completo.md

Difere de generate_sql.py (lote de 10/08) em tres pontos: usa
transform.normalizar_telefone_canonico (injeta o 9o digito), cria funil +
etapas + deals, e nao tem curadoria manual de saudacao nem score de ICP.
"""
import csv
import json
import re
from collections import namedtuple

import transform

LOTE = "reativacao_bling_2026-08-14"
ORIGEM = "reativacao_bling"
AUTOR_NOTA = "Sistema — Reativação Bling"
PREFIXO_BRIEFING = "REATIVAÇÃO BLING 14/08/2026 — lote reativacao_bling_2026-08-14"

# UUIDs hardcoded: deixam os INSERTs idempotentes e dao ao rollback um alvo
# preciso. O de TAG_DEBITO_VENCIDO e referenciado pelo frontend
# (frontend/src/lib/constants.ts) — mudar aqui exige mudar la.
PIPELINE_ID = "b2f9c31d-8a47-4e26-95c0-3d7a1f6e8b09"
PIPELINE_NOME = "Reativação Bling"

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

Coorte = namedtuple("Coorte", "novos ja_no_crm sem_telefone duplicados_no_csv")


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
    ja_no_crm = sem_telefone = duplicados = 0
    for linha in linhas:
        fone = telefone_da_linha(linha)
        if not fone:
            sem_telefone += 1
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
    return Coorte(novos, ja_no_crm, sem_telefone, duplicados)


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

    NOT EXISTS em vez de ON CONFLICT porque nao ha garantia de constraint
    unica em lead_tags(lead_id, tag_id).
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

    owner_user_id NULL e is_universal false seguem o padrao dos funis da
    Valeria: visiveis para todos, sem dono designado (decisao D3 do spec —
    numero, template e dono sao decididos quando a campanha for montada).
    """
    partes = [
        "-- Funil do lote e suas etapas",
        "INSERT INTO pipelines (id, name, order_index, owner_user_id, is_universal)",
        "VALUES (%s, %s, 99, NULL, false)" % (
            sql_literal(PIPELINE_ID), sql_literal(PIPELINE_NOME)),
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
