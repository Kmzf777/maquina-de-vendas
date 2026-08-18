"""Identidade de cliente: casar lead do CRM com contato do Bling sem duplicar.

O PROBLEMA: o CRM normaliza telefone para E.164 ("5551992696163"); o Bling
guarda texto livre formatado ("(51) 99269-6163"). Casar por telefone criaria
contatos duplicados no ERP. Pior: o telefone do lead costuma ser o do COMPRADOR
(uma pessoa), enquanto o contato do Bling e a EMPRESA.

A SOLUCAO, em quatro camadas:
  1. CPF/CNPJ (so digitos) e a chave. Unico identificador canonico dos dois lados.
  2. O vinculo e PERSISTIDO em `leads.bling_contact_id`, sob indice UNIQUE
     parcial. Resolvido uma vez por cliente, para sempre.
  3. Telefone e e-mail apenas SUGEREM — exigem confirmacao humana.
  4. Antes de criar, lock por documento + re-checagem AO VIVO na API.
"""
import asyncio
import logging
import secrets
from dataclasses import dataclass, field

import redis.asyncio as aioredis

from app.bling import config
from app.bling.errors import BlingValidationError
from app.bling.sync import _to_e164_br, map_contact
from app.config import settings
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

_LOCK_TTL = 30
_redis: aioredis.Redis | None = None

# Colunas do espelho que descrevem um candidato ao vendedor na tela de escolha.
_CONTACT_COLS = "id, nome, fantasia, doc_digits, email, telefone_e164, celular_e164"


@dataclass
class Resolution:
    """Resultado da resolucao de identidade.

    status:
      linked    — vinculado (determinístico). `contact_id` preenchido.
      ambiguous — mais de um contato com o mesmo documento. Decide o humano.
      suggested — casou por telefone/e-mail. Precisa de confirmacao.
      missing   — nao existe contato correspondente. Fluxo de criacao.
    """
    status: str
    contact_id: int | None = None
    candidates: list[dict] = field(default_factory=list)
    reason: str = ""


def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            settings.redis_url, decode_responses=True,
            socket_connect_timeout=2, socket_timeout=2,
        )
    return _redis


def _lock(key: str):
    """Lock Redis simples com liberacao por token (padrao do buffer/lead_lock).

    Diferenca IMPORTANTE em relacao ao `lead_run_lock`: aquele e fail-open (se o
    Redis cair, o atendimento segue sem trava, porque bloquear o lead e pior).
    Aqui NAO pode ser: seguir sem serializacao significa dois POST /contatos com o
    mesmo documento — duplicata no ERP, exatamente o que este modulo existe para
    impedir. Quem nao consegue a trava recebe False e o chamador recusa a operacao.
    """
    client = _get_redis()
    token = secrets.token_hex(8)

    class _Ctx:
        owned = False

        async def __aenter__(self):
            for _ in range(60):
                if await client.set(key, token, nx=True, ex=_LOCK_TTL):
                    self.owned = True
                    return True
                await asyncio.sleep(0.5)
            return False

        async def __aexit__(self, *_a):
            if self.owned:
                # Lua: so deleta se o valor ainda for o NOSSO token — uma trava que
                # expirou por TTL nao pode apagar a trava de quem ja reassumiu.
                lua = ("if redis.call('get', KEYS[1]) == ARGV[1] then "
                       "return redis.call('del', KEYS[1]) else return 0 end")
                await client.eval(lua, 1, key, token)
            return False

    return _Ctx()


# --------------------------------------------------------------------------
# Documento
# --------------------------------------------------------------------------
def doc_digits(value: str | None) -> str | None:
    if not value:
        return None
    out = "".join(ch for ch in value if ch.isdigit())
    return out or None


def _cpf_ok(d: str) -> bool:
    if len(set(d)) == 1:
        return False
    for tamanho in (9, 10):
        soma = sum(int(d[i]) * ((tamanho + 1) - i) for i in range(tamanho))
        dv = (soma * 10) % 11 % 10
        if dv != int(d[tamanho]):
            return False
    return True


def _cnpj_ok(d: str) -> bool:
    if len(set(d)) == 1:
        return False
    pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    pesos2 = [6] + pesos1
    for pesos, pos in ((pesos1, 12), (pesos2, 13)):
        soma = sum(int(d[i]) * pesos[i] for i in range(pos))
        resto = soma % 11
        dv = 0 if resto < 2 else 11 - resto
        if dv != int(d[pos]):
            return False
    return True


def is_valid_document(value: str | None) -> bool:
    """CPF (11) ou CNPJ (14) com digito verificador correto.

    Validar o DV importa: um documento digitado errado nao acha o contato
    existente e cria um duplicado — exatamente o que queremos evitar.
    """
    d = doc_digits(value)
    if not d:
        return False
    if len(d) == 11:
        return _cpf_ok(d)
    if len(d) == 14:
        return _cnpj_ok(d)
    return False


# --------------------------------------------------------------------------
# Resolucao
# --------------------------------------------------------------------------
def _phone_variants(lead: dict) -> list[str]:
    """Telefones do lead na MESMA normalizacao usada no espelho de contatos.

    Usa `_to_e164_br` (de app.bling.sync), nao `normalize_phone` puro, porque e
    `_to_e164_br` que preenche `bling_contacts.telefone_e164`/`celular_e164`. A
    diferenca entre as duas e o DDI: `normalize_phone("(51) 99269-6163")` devolve
    "51992696163" (sem o 55) e `_to_e164_br` devolve "5551992696163". Usar
    normalizacoes diferentes nos dois lados faria o casamento por telefone falhar
    em SILENCIO — o lead viraria "missing" e o vendedor cadastraria de novo um
    cliente que ja existe no ERP.

    Bonus do contrato de `_to_e164_br`: devolve None para formato desconhecido,
    entao BSUID do WhatsApp ("US.1349...") e lixo de importacao nunca viram chave
    de busca. Melhor "sem telefone" do que um telefone que casa com outro cliente.
    """
    brutos = [lead.get("phone"), lead.get("telefone_comercial")]
    saida = []
    for bruto in brutos:
        norm = _to_e164_br(bruto)
        if norm and norm not in saida:
            saida.append(norm)
    return saida


def _query_by_doc(doc: str) -> list[dict]:
    res = (get_supabase().table("bling_contacts")
           .select(_CONTACT_COLS)
           .eq("doc_digits", doc).limit(10).execute())
    return getattr(res, "data", None) or []


def _query_by_phones(phones: list[str]) -> list[dict]:
    if not phones:
        return []
    # Interpolar direto na expressao do PostgREST so e seguro porque `_phone_variants`
    # devolve exclusivamente digitos (`_to_e164_br` descarta qualquer outro formato).
    # Se um dia essa garantia mudar, aqui vira ponto de injecao no filtro.
    lista = ",".join(phones)
    res = (get_supabase().table("bling_contacts")
           .select(_CONTACT_COLS)
           .or_(f"telefone_e164.in.({lista}),celular_e164.in.({lista})")
           .limit(10).execute())
    return getattr(res, "data", None) or []


def _query_by_email(email: str) -> list[dict]:
    res = (get_supabase().table("bling_contacts")
           .select(_CONTACT_COLS)
           .eq("email", email).limit(10).execute())
    return getattr(res, "data", None) or []


def _link(lead_id: str, contact_id: int) -> None:
    (get_supabase().table("leads")
     .update({"bling_contact_id": contact_id}).eq("id", lead_id).execute())


async def resolve(lead: dict) -> Resolution:
    """Resolve o contato Bling de um lead. Ver docstring do modulo."""
    if lead.get("bling_contact_id"):
        return Resolution("linked", int(lead["bling_contact_id"]), reason="vinculo_existente")

    doc = doc_digits(lead.get("cnpj"))
    if doc:
        achados = await asyncio.to_thread(_query_by_doc, doc)
        if len(achados) == 1:
            contact_id = int(achados[0]["id"])
            await asyncio.to_thread(_link, lead["id"], contact_id)
            return Resolution("linked", contact_id, reason="documento")
        if len(achados) > 1:
            # Dois contatos com o mesmo CPF/CNPJ e sujeira no ERP. Escolher um
            # por conta propria significa lancar a venda no cadastro errado.
            return Resolution("ambiguous", None, achados, reason="documento_duplicado")

    achados = await asyncio.to_thread(_query_by_phones, _phone_variants(lead))
    if achados:
        # SUGGESTED, nunca LINKED: nada e gravado aqui. O telefone do lead e do
        # comprador; o contato do Bling e a empresa. So o humano confirma.
        return Resolution("suggested", None, achados, reason="telefone")

    email = (lead.get("email") or "").strip().lower()
    if email:
        achados = await asyncio.to_thread(_query_by_email, email)
        if achados:
            return Resolution("suggested", None, achados, reason="email")

    return Resolution("missing", None, [], reason="sem_correspondencia")


async def link(lead_id: str, contact_id: int) -> None:
    """Confirma manualmente o vinculo (usado quando o vendedor escolhe candidato)."""
    await asyncio.to_thread(_link, lead_id, contact_id)


# --------------------------------------------------------------------------
# Criacao
# --------------------------------------------------------------------------
def _upsert_mirror(row: dict) -> None:
    (get_supabase().table("bling_contacts")
     .upsert(map_contact(row), on_conflict="id").execute())


async def create_contact(client, lead: dict, dados: dict) -> int:
    """Cria (ou reaproveita) o contato no Bling e devolve o id.

    `dados` vem do modal: nome, numeroDocumento, tipo, email, telefone, celular,
    endereco{geral{...}}.
    """
    doc = doc_digits(dados.get("numeroDocumento"))
    if not is_valid_document(doc):
        raise BlingValidationError(
            "Documento (CPF/CNPJ) valido e obrigatorio para cadastrar o cliente no Bling",
            type_="MISSING_REQUIRED_FIELD_ERROR",
            description="Sem documento nao ha chave unica e o contato duplicaria no ERP.",
            status=422,
        )

    async with _lock(f"lock:bling_contact:{doc}") as owned:
        if not owned:
            raise BlingValidationError(
                "outro cadastro deste mesmo cliente esta em andamento; tente de novo",
                status=409,
            )

        # Re-checagem AO VIVO: o espelho pode estar minutos atrasado.
        vivo = await client.get("/contatos", {"numeroDocumento": doc})
        existentes = vivo.get("data") or []
        if existentes:
            if len(existentes) > 1:
                # O ERP ja tem duplicata para este documento. Vincular ao primeiro
                # nao e ideal, mas criar um TERCEIRO cadastro seria pior. Fica o
                # aviso no log para limpeza manual no Bling.
                logger.warning(
                    "[BLING] %d contatos com o documento %s no Bling — vinculando ao "
                    "primeiro (%s); duplicata precisa de limpeza manual no ERP",
                    len(existentes), doc, existentes[0].get("id"),
                )
            contact_id = int(existentes[0]["id"])
            logger.info("[BLING] contato %s ja existia para doc %s — vinculando",
                        contact_id, doc)
        else:
            payload = {
                "nome": dados.get("nome") or lead.get("name") or "",
                "tipo": dados.get("tipo") or ("J" if len(doc) == 14 else "F"),
                "situacao": "A",
                "numeroDocumento": doc,
            }
            for campo in ("fantasia", "email", "telefone", "celular", "ie",
                          "indicadorIe", "endereco"):
                if dados.get(campo):
                    payload[campo] = dados[campo]
            criado = await client.post("/contatos", payload)
            contact_id = int((criado.get("data") or {})["id"])
            logger.info("[BLING] contato %s criado para doc %s", contact_id, doc)

        await asyncio.to_thread(_upsert_mirror, {
            "id": contact_id,
            "nome": dados.get("nome") or lead.get("name") or "",
            "tipo": dados.get("tipo"),
            "numeroDocumento": doc,
            "telefone": dados.get("telefone"),
            "celular": dados.get("celular"),
            "email": dados.get("email"),
            "situacao": "A",
            "endereco": dados.get("endereco"),
        })
        await asyncio.to_thread(_link, lead["id"], contact_id)
        return contact_id


# --------------------------------------------------------------------------
# Caminho inverso: contato do Bling sem lead no CRM
# --------------------------------------------------------------------------
def _find_lead(coluna: str, valor) -> str | None:
    res = (get_supabase().table("leads").select("id")
           .eq(coluna, valor).limit(1).execute())
    linhas = getattr(res, "data", None) or []
    return linhas[0]["id"] if linhas else None


def _insert_lead(payload: dict) -> str | None:
    res = get_supabase().table("leads").insert(payload).execute()
    linhas = getattr(res, "data", None) or []
    return linhas[0]["id"] if linhas else None


async def ensure_lead(contato: dict) -> str | None:
    """Devolve o lead_id do contato, criando o lead se preciso (decisao D6)."""
    contact_id = int(contato["id"])

    achado = await asyncio.to_thread(_find_lead, "bling_contact_id", contact_id)
    if achado:
        return achado

    doc = contato.get("doc_digits")
    if doc:
        achado = await asyncio.to_thread(_find_lead, "cnpj", doc)
        if achado:
            await asyncio.to_thread(_link, achado, contact_id)
            return achado

    telefone = contato.get("celular_e164") or contato.get("telefone_e164")
    if telefone:
        # ASSIMETRIA PROPOSITAL com `resolve`: la, telefone so SUGERE; aqui ele
        # VINCULA. Os riscos sao opostos. `resolve` decide em que cadastro do ERP
        # a venda entra — errar emite nota no CNPJ errado. Aqui nada e escrito no
        # ERP: so escolhemos a que lead do CRM o contato se prende. E `leads.phone`
        # e UNIQUE: nao reaproveitar o lead achado nao seria "mais seguro", seria
        # estourar a constraint no insert logo abaixo.
        achado = await asyncio.to_thread(_find_lead, "phone", telefone)
        if achado:
            await asyncio.to_thread(_link, achado, contact_id)
            return achado

    endereco = contato.get("endereco") or {}
    partes = [endereco.get("municipio"), endereco.get("uf")]
    payload = {
        # leads.phone e UNIQUE NOT NULL. Sem telefone, um placeholder unico por
        # construcao. A coluna ja aceita valores nao-E.164 (BSUIDs do WhatsApp).
        "phone": telefone or f"bling-{contact_id}",
        "name": contato.get("fantasia") or contato.get("nome"),
        "company": contato.get("nome"),
        "razao_social": contato.get("nome"),
        "nome_fantasia": contato.get("fantasia"),
        "cnpj": doc,
        "email": contato.get("email"),
        "endereco": " - ".join([p for p in partes if p]) or None,
        "stage": config.lead_default_stage(),
        "status": "ativo",
        "channel": "bling",
        "bling_contact_id": contact_id,
        "metadata": {"origem": "bling_webhook", "id_bling": str(contact_id)},
    }
    lead_id = await asyncio.to_thread(_insert_lead, payload)
    logger.info("[BLING] lead %s criado a partir do contato %s", lead_id, contact_id)
    return lead_id
