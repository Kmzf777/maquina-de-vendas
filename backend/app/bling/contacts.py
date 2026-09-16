"""Identidade de cliente: casar lead do CRM com contato do Bling sem duplicar.

O PROBLEMA: o CRM normaliza telefone para E.164 ("5551992696163"); o Bling
guarda texto livre formatado ("(51) 99269-6163"). Casar por telefone criaria
contatos duplicados no ERP. Pior: o telefone do lead costuma ser o do COMPRADOR
(uma pessoa), enquanto o contato do Bling e a EMPRESA.

A SOLUCAO, em quatro camadas:
  1. CPF/CNPJ (so digitos) e a chave. Unico identificador canonico dos dois lados.
  2. O vinculo e PERSISTIDO em `lead_bling_contacts` (uma linha por lead+conta),
     sob indice UNIQUE em (account, bling_contact_id). Resolvido uma vez por
     cliente POR CONTA, para sempre — o mesmo lead pode ter contato na conta 1 e
     outro na conta 2, porque o mesmo cliente pode existir nos dois CNPJs com
     IDs diferentes ("alguns clientes em comum", o caso que motivou a segunda
     conta).
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
      linked    — vinculado (deterministico). `contact_id` preenchido.
      ambiguous — mais de um contato com o mesmo documento, OU o contato certo ja
                  pertence a outro lead. Nos dois casos decide o humano.
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


def _query_by_doc(doc: str, account: str) -> list[dict]:
    res = (get_supabase().table("bling_contacts")
           .select(_CONTACT_COLS)
           .eq("doc_digits", doc).eq("account", account).limit(10).execute())
    return getattr(res, "data", None) or []


def _query_by_phones(phones: list[str], account: str) -> list[dict]:
    if not phones:
        return []
    # Interpolar direto na expressao do PostgREST so e seguro porque `_phone_variants`
    # devolve exclusivamente digitos (`_to_e164_br` descarta qualquer outro formato).
    # Se um dia essa garantia mudar, aqui vira ponto de injecao no filtro.
    lista = ",".join(phones)
    res = (get_supabase().table("bling_contacts")
           .select(_CONTACT_COLS)
           .eq("account", account)
           .or_(f"telefone_e164.in.({lista}),celular_e164.in.({lista})")
           .limit(10).execute())
    return getattr(res, "data", None) or []


def _query_by_email(email: str, account: str) -> list[dict]:
    res = (get_supabase().table("bling_contacts")
           .select(_CONTACT_COLS)
           .eq("email", email).eq("account", account).limit(10).execute())
    return getattr(res, "data", None) or []


def _contato_do_lead(lead_id: str, account: str) -> int | None:
    """Contato do lead NESTA conta, ou None.

    Substitui a leitura direta de `leads.bling_contact_id`. O recorte por conta e
    o ponto inteiro: um lead pode ter contato na conta 1 e nenhum na conta 2, e os
    dois estados sao independentes — por isso `resolve` e
    `_pode_vincular_por_telefone` tem que perguntar por ESTA conta, nunca "o lead
    tem vinculo em qualquer conta" (a armadilha central desta migracao).
    """
    res = (get_supabase().table("lead_bling_contacts").select("bling_contact_id")
           .eq("lead_id", lead_id).eq("account", account)
           .limit(1).maybe_single().execute())
    linha = getattr(res, "data", None) or {}
    return linha.get("bling_contact_id")


def _link(lead_id: str, contact_id: int, account: str) -> None:
    (get_supabase().table("lead_bling_contacts").upsert({
        "lead_id": lead_id,
        "account": account,
        "bling_contact_id": contact_id,
    }, on_conflict="lead_id,account").execute())


def _e_violacao_de_unicidade(exc: Exception) -> bool:
    """A violacao veio do indice UNIQUE
    `lead_bling_contacts_account_contact_key` em (account, bling_contact_id)
    (SQLSTATE 23505)?

    Dois leads com o mesmo CNPJ e plausivel (matriz e filial cadastradas separado,
    lead duplicado por importacao). O primeiro a resolver fica com o contato
    NESTA conta; o segundo bate no indice. Isso NAO e bug — e informacao — mas
    sem tratamento vira 500 opaco, e em `create_contact` vira laco de falha
    permanente: o contato ja existe, entao toda tentativa futura repete GET →
    acha → `_link` → 500.

    Checa `code` e o texto porque a pista depende da versao do supabase-py/postgrest.
    """
    codigo = getattr(exc, "code", "") or ""
    texto = f"{codigo} {exc}".lower()
    return "23505" in texto or "duplicate key" in texto


async def resolve(lead: dict, account: str = config.DEFAULT_ACCOUNT) -> Resolution:
    """Resolve o contato Bling de um lead, NESTA conta. Ver docstring do modulo.

    O recorte por conta e o que viabiliza o "cliente em comum": o mesmo lead pode
    estar `linked` na conta 1 e `missing`/`suggested` na conta 2 ao mesmo tempo —
    os dois estados moram em linhas diferentes de `lead_bling_contacts`, nunca no
    lead. Por isso o primeiro passo NUNCA olha vinculo de outra conta.
    """
    ja_vinculado = await asyncio.to_thread(_contato_do_lead, lead["id"], account)
    if ja_vinculado:
        return Resolution("linked", int(ja_vinculado), reason="vinculo_existente")

    doc = doc_digits(lead.get("cnpj"))
    # O DV e validado ANTES de o documento virar chave. Este e o unico ramo que
    # vincula sozinho e GRAVA, entao a chave precisa ser digna disso. Numa base
    # importada de ERP (os 1.208 leads da reativacao) o campo vem com placeholder
    # ("00000000000", "1") e digitacao errada — lixo casa com lixo igual no espelho
    # e produziria vinculo permanente nascido de nada. Documento invalido nao para
    # o fluxo: cai para telefone/e-mail, que so sugerem.
    if doc and is_valid_document(doc):
        achados = await asyncio.to_thread(_query_by_doc, doc, account)
        if len(achados) == 1:
            contact_id = int(achados[0]["id"])
            try:
                await asyncio.to_thread(_link, lead["id"], contact_id, account)
            except Exception as exc:
                if not _e_violacao_de_unicidade(exc):
                    raise
                # O contato ja e de outro lead NESTA conta. Nao ha escolha
                # automatica certa: devolve para o humano em vez de estourar 500
                # sem diagnostico.
                logger.warning(
                    "[BLING] contato %s ja vinculado a outro lead na conta %s — "
                    "%s fica para decisao humana", contact_id, account, lead.get("id"),
                )
                return Resolution("ambiguous", None, achados,
                                  reason="contato_ja_vinculado")
            return Resolution("linked", contact_id, reason="documento")
        if len(achados) > 1:
            # Dois contatos com o mesmo CPF/CNPJ e sujeira no ERP. Escolher um
            # por conta propria significa lancar a venda no cadastro errado.
            return Resolution("ambiguous", None, achados, reason="documento_duplicado")

    achados = await asyncio.to_thread(_query_by_phones, _phone_variants(lead), account)
    if achados:
        # SUGGESTED, nunca LINKED: nada e gravado aqui. O telefone do lead e do
        # comprador; o contato do Bling e a empresa. So o humano confirma.
        return Resolution("suggested", None, achados, reason="telefone")

    email = (lead.get("email") or "").strip().lower()
    if email:
        achados = await asyncio.to_thread(_query_by_email, email, account)
        if achados:
            return Resolution("suggested", None, achados, reason="email")

    return Resolution("missing", None, [], reason="sem_correspondencia")


async def link(lead_id: str, contact_id: int,
                account: str = config.DEFAULT_ACCOUNT) -> None:
    """Confirma manualmente o vinculo NESTA conta (usado quando o vendedor
    escolhe candidato). O mesmo lead pode ter uma linha em `lead_bling_contacts`
    por conta — vincular na conta 2 nunca apaga nem troca o vinculo da conta 1."""
    await asyncio.to_thread(_link, lead_id, contact_id, account)


def _unlink(lead_id: str, account: str) -> None:
    (get_supabase().table("lead_bling_contacts").delete()
     .eq("lead_id", lead_id).eq("account", account).execute())


async def unlink(lead_id: str, account: str = config.DEFAULT_ACCOUNT) -> None:
    """Desfaz o vinculo do lead NESTA conta. Verbo proprio, e nao `link` com nulo,
    porque desvincular tem consequencia diferente: a proxima venda do lead nesta
    conta volta a cair na resolucao por documento. O vinculo de OUTRA conta nunca
    e tocado — cada linha de `lead_bling_contacts` e independente por conta."""
    await asyncio.to_thread(_unlink, lead_id, account)


# --------------------------------------------------------------------------
# Criacao
# --------------------------------------------------------------------------
def _upsert_mirror(row: dict, account: str) -> None:
    linha = map_contact(row)
    linha["account"] = account
    (get_supabase().table("bling_contacts")
     .upsert(linha, on_conflict="account,id").execute())


async def create_contact(client, lead: dict, dados: dict,
                          account: str = config.DEFAULT_ACCOUNT) -> int:
    """Cria (ou reaproveita) o contato no Bling e devolve o id.

    `dados` vem do modal: nome, numeroDocumento, tipo, email, telefone, celular,
    endereco{geral{...}}. `client` ja e um `BlingClient` desta `account` — a
    chamada HTTP cai na conta certa sozinha; aqui so precisamos repassar a conta
    para o espelho e para o vinculo do lead.
    """
    doc = doc_digits(dados.get("numeroDocumento"))
    if not is_valid_document(doc):
        raise BlingValidationError(
            "Documento (CPF/CNPJ) valido e obrigatorio para cadastrar o cliente no Bling",
            type_="MISSING_REQUIRED_FIELD_ERROR",
            description="Sem documento nao ha chave unica e o contato duplicaria no ERP.",
            status=422,
        )

    # O lock leva a conta: o mesmo documento pode legitimamente virar DOIS
    # contatos distintos (um por conta, ERPs separados). Sem a conta na chave, uma
    # criacao na conta 2 esperaria a trava da conta 1 sem necessidade nenhuma —
    # sao operacoes independentes contra APIs independentes.
    async with _lock(f"lock:bling_contact:{account}:{doc}") as owned:
        if not owned:
            raise BlingValidationError(
                "outro cadastro deste mesmo cliente esta em andamento; tente de novo",
                status=409,
            )

        # Re-checagem AO VIVO: o espelho pode estar minutos atrasado.
        vivo = await client.get("/contatos", {"numeroDocumento": doc})
        # E NAO confia no filtro do servidor: reconfere o documento item a item. Se
        # o Bling ignorar `numeroDocumento` — parametro desconhecido, REST costuma
        # devolver a colecao inteira em vez de erro — `data[0]` seria um contato
        # QUALQUER da conta, e vincularia o cliente a ele. Falha silenciosa e
        # catastrofica, no ponto exato que existe para impedir duplicata.
        existentes = [c for c in (vivo.get("data") or [])
                      if doc_digits(c.get("numeroDocumento")) == doc]
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
        }, account)
        try:
            await asyncio.to_thread(_link, lead["id"], contact_id, account)
        except Exception as exc:
            if not _e_violacao_de_unicidade(exc):
                raise
            # Sem isto o vendedor entra num laco de falha permanente: o contato ja
            # existe no Bling, entao cada nova tentativa refaz GET → acha → 500.
            raise BlingValidationError(
                "este contato do Bling ja esta vinculado a outro lead",
                type_="CONFLICT",
                description=(
                    f"O contato {contact_id} pertence a outro lead do CRM. "
                    "Abra o lead existente ou desfaca o vinculo antes de continuar."
                ),
                status=409,
            ) from exc
        return contact_id


# --------------------------------------------------------------------------
# Caminho inverso: contato do Bling sem lead no CRM
# --------------------------------------------------------------------------
def _find_lead(coluna: str, valor) -> dict | None:
    """Devolve a LINHA do lead, nao so o id.

    `cnpj` vem junto porque quem chama precisa dele para decidir se pode gravar o
    vinculo — reaproveitar a linha e gravar o vinculo sao decisoes separadas. Ver
    `_pode_vincular_por_telefone`. `bling_contact_id` NAO entra mais na projecao:
    o vinculo mora em `lead_bling_contacts`, por conta — quem precisa dele chama
    `_contato_do_lead`.
    """
    res = (get_supabase().table("leads").select("id, cnpj")
           .eq(coluna, valor).limit(1).execute())
    linhas = getattr(res, "data", None) or []
    return linhas[0] if linhas else None


def _pode_vincular_por_telefone(lead_row: dict, doc_contato: str | None,
                                 contato_da_conta: int | None) -> bool:
    """O telefone bateu — mas isso autoriza GRAVAR o vinculo neste lead, NESTA conta?

    Duas recusas, as duas por motivo de nota fiscal:

    1. O lead JA tem contato NESTA CONTA (`contato_da_conta is not None`). Esse
       vinculo veio de documento (unico ramo que vincula sozinho) ou de
       confirmacao humana. Um palpite de telefone nunca o substitui: o lead
       passaria a apontar para outro cadastro NESTA conta e a proxima venda
       sairia no CNPJ errado. O indice UNIQUE nao protege disso — ele impede
       dois leads apontarem para o mesmo contato, nao um lead trocar de contato.
       IMPORTANTE: contato em OUTRA conta nao entra aqui — bloquear por causa
       dela reabriria a armadilha central desta entrega, o "cliente em comum"
       que nunca conseguiria vinculo na segunda conta.
    2. Os documentos existem dos dois lados e DIVERGEM. Documentos diferentes sao
       clientes diferentes, por mais que o telefone bata: numero compartilhado
       (matriz, escritorio do contador, celular do socio que responde por duas
       empresas) e comum na base real.

    Nos dois casos o lead ainda e REAPROVEITADO (devolvemos o id, nao duplicamos);
    so o vinculo NESTA conta e que nao e gravado.
    """
    if contato_da_conta is not None:
        return False
    doc_lead = doc_digits(lead_row.get("cnpj"))
    if doc_lead and doc_contato and doc_lead != doc_contato:
        return False
    return True


def _insert_lead(payload: dict) -> str | None:
    res = get_supabase().table("leads").insert(payload).execute()
    linhas = getattr(res, "data", None) or []
    return linhas[0]["id"] if linhas else None


def _lead_por_contato(contact_id: int, account: str) -> dict | None:
    """Lead dono deste contato, NESTA conta. Substitui
    `_find_lead("bling_contact_id", contact_id)`, que nao existe mais como
    coluna — o mesmo `contact_id` pode pertencer a leads DIFERENTES em contas
    diferentes, entao a busca precisa ser sempre por (conta, contato).
    """
    res = (get_supabase().table("lead_bling_contacts").select("lead_id")
           .eq("bling_contact_id", contact_id).eq("account", account)
           .limit(1).maybe_single().execute())
    linha = getattr(res, "data", None) or {}
    if not linha.get("lead_id"):
        return None
    return _find_lead("id", linha["lead_id"])


async def ensure_lead(contato: dict, account: str = config.DEFAULT_ACCOUNT) -> str | None:
    """Devolve o lead_id do contato NESTA conta, criando o lead se preciso
    (decisao D6). A logica de casamento (documento -> celular -> criar) nao
    muda: so o lugar onde o vinculo e lido/gravado passa a ser por conta.
    """
    contact_id = int(contato["id"])

    achado = await asyncio.to_thread(_lead_por_contato, contact_id, account)
    if achado:
        return achado["id"]

    doc = contato.get("doc_digits")
    if doc:
        achado = await asyncio.to_thread(_find_lead, "cnpj", doc)
        if achado:
            # Mesmo casando por documento, nao regrava vinculo ja existente NESTA
            # conta: o lead pode estar preso a OUTRO contato desta mesma conta
            # (documento duplicado no ERP), e trocar por baixo mandaria a proxima
            # venda para o cadastro errado. Contato em OUTRA conta nao bloqueia —
            # so o vinculo desta conta importa aqui.
            contato_da_conta = await asyncio.to_thread(
                _contato_do_lead, achado["id"], account)
            if contato_da_conta is None:
                await asyncio.to_thread(_link, achado["id"], contact_id, account)
            return achado["id"]

    # SO celular como chave, nunca o fixo: um fixo de empresa e compartilhado entre
    # varios contatos do Bling, e aqui o telefone GRAVA vinculo — prenderia leads
    # distintos ao mesmo cadastro. O fixo continua no espelho
    # (`bling_contacts.telefone_e164`), entao nada se perde. Em `_query_by_phones`
    # o fixo pode entrar, porque la o resultado so SUGERE.
    telefone = contato.get("celular_e164")
    if telefone:
        # ASSIMETRIA PROPOSITAL com `resolve`: la, telefone so SUGERE; aqui pode
        # gravar. Os riscos sao opostos — `resolve` decide em que cadastro do ERP a
        # venda entra, enquanto aqui nada e escrito no ERP — e `leads.phone` e
        # UNIQUE, entao ignorar o lead achado nao seria "mais seguro", seria
        # estourar a constraint no insert. Mas gravar o vinculo continua sendo uma
        # decisao separada de reaproveitar a linha: ver `_pode_vincular_por_telefone`.
        achado = await asyncio.to_thread(_find_lead, "phone", telefone)
        if achado:
            contato_da_conta = await asyncio.to_thread(
                _contato_do_lead, achado["id"], account)
            if _pode_vincular_por_telefone(achado, doc, contato_da_conta):
                await asyncio.to_thread(_link, achado["id"], contact_id, account)
            return achado["id"]

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
        "metadata": {"origem": "bling_webhook", "id_bling": str(contact_id)},
    }
    lead_id = await asyncio.to_thread(_insert_lead, payload)
    if lead_id:
        # Vinculo e escrita SEPARADA da criacao do lead (tabela diferente agora),
        # entao so grava se o insert de fato devolveu um id — sem lead nao ha o
        # que vincular.
        await asyncio.to_thread(_link, lead_id, contact_id, account)
    logger.info("[BLING] lead %s criado a partir do contato %s (conta %s)",
                lead_id, contact_id, account)
    return lead_id
