# backend-recuperar-lead Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Criar o serviço `backend-recuperar-lead` — um SDR proativo baseado no `backend-evolution` que aborda leads ociosos via API oficial Meta, os qualifica e entrega ao vendedor humano.

**Architecture:** Fork completo do `backend-evolution` com: (1) prompt `secretaria` reescrito para outbound comercial, (2) `build_base_prompt` com `lead_context` opcional, (3) check de `human_control` no processor para bloquear agent após entrega ao vendedor, (4) módulo `outbound/` com dispatcher de template hardcoded e endpoint REST.

**Tech Stack:** Python 3.12, FastAPI, OpenAI GPT-4.1/4.1-mini, Supabase, Redis, Meta Cloud API (httpx), pydantic-settings.

**Spec:** `docs/superpowers/specs/2026-04-13-backend-recuperar-lead-design.md`

---

## File Map

| Arquivo | Ação | Responsabilidade |
|---|---|---|
| `backend-recuperar-lead/` | Criar (fork) | Cópia completa do backend-evolution |
| `app/config.py` | Modificar | Adicionar `meta_access_token`, `meta_phone_number_id` |
| `app/agent/prompts/secretaria.py` | Reescrever | Prompt SDR outbound — Valeria abordando, não recebendo |
| `app/agent/prompts/base.py` | Modificar | `build_base_prompt()` aceita `lead_context: dict \| None` |
| `app/agent/orchestrator.py` | Modificar | Passa `lead_context`; remove guardrail automático de stage |
| `app/buffer/processor.py` | Modificar | Checa `human_control` antes de rodar agent |
| `app/outbound/__init__.py` | Criar | Módulo vazio |
| `app/outbound/dispatcher.py` | Criar | Envia template hardcoded via Meta Cloud API |
| `app/outbound/router.py` | Criar | `POST /api/outbound/dispatch` |
| `app/main.py` | Modificar | Inclui outbound router |
| `tests/test_base_prompt.py` | Criar | Testa build_base_prompt com e sem lead_context |
| `tests/test_processor_human_control.py` | Criar | Testa bloqueio do agent quando human_control=True |
| `tests/test_dispatcher.py` | Criar | Testa dispatcher (mock httpx) |

---

## Task 1: Fork do backend-evolution

**Files:**
- Criar: `backend-recuperar-lead/` (cópia completa de `backend-evolution/`)

- [ ] **Step 1: Copiar o diretório**

```bash
cp -r backend-evolution backend-recuperar-lead
```

- [ ] **Step 2: Verificar estrutura copiada**

```bash
ls backend-recuperar-lead/app/
```

Esperado: `agent  broadcast  buffer  cadence  campaign  channels  config.py  db  humanizer  leads  main.py  photos  stats  webhook  whatsapp`

- [ ] **Step 3: Remover cache Python**

```bash
find backend-recuperar-lead -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; echo "ok"
```

- [ ] **Step 4: Criar .env de exemplo**

Criar `backend-recuperar-lead/.env.example`:

```
OPENAI_API_KEY=sk-...
SUPABASE_URL=https://tshmvxxxyxgctrdkqvam.supabase.co
SUPABASE_SERVICE_KEY=eyJhbGci...
REDIS_URL=redis://localhost:6379
API_BASE_URL=https://sdr.canastrainteligencia.com
FRONTEND_URL=http://localhost:3000
META_ACCESS_TOKEN=EAAXEks7lg7IB...
META_PHONE_NUMBER_ID=1049315514934778
```

- [ ] **Step 5: Commit do fork**

```bash
cd /home/Kelwin/Maquinadevendascanastra
git add backend-recuperar-lead/
git commit -m "chore: fork backend-evolution as backend-recuperar-lead"
```

---

## Task 2: Adicionar Meta env vars ao config.py

**Files:**
- Modificar: `backend-recuperar-lead/app/config.py`

- [ ] **Step 1: Ler o arquivo atual**

```bash
cat backend-recuperar-lead/app/config.py
```

- [ ] **Step 2: Adicionar campos Meta**

Substituir o bloco `class Settings` para incluir:

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Evolution API (optional — per-channel config used instead)
    evolution_api_url: str = ""
    evolution_api_key: str = ""
    evolution_instance: str = ""

    # OpenAI
    openai_api_key: str

    # Supabase
    supabase_url: str
    supabase_service_key: str

    # Redis
    redis_url: str = "redis://localhost:6379"

    # App
    api_base_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:3000"

    # Buffer
    buffer_base_timeout: int = 15
    buffer_extend_timeout: int = 10
    buffer_max_timeout: int = 45

    # Meta Cloud API — used by outbound dispatcher
    meta_access_token: str = ""
    meta_phone_number_id: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


class _SettingsProxy:
    def __getattr__(self, name: str):
        return getattr(get_settings(), name)


settings = _SettingsProxy()  # type: ignore
```

- [ ] **Step 3: Commit**

```bash
cd /home/Kelwin/Maquinadevendascanastra
git add backend-recuperar-lead/app/config.py
git commit -m "feat(recuperar-lead): add meta_access_token and meta_phone_number_id to config"
```

---

## Task 3: Atualizar base.py — lead_context opcional

**Files:**
- Modificar: `backend-recuperar-lead/app/agent/prompts/base.py`
- Criar: `backend-recuperar-lead/tests/test_base_prompt.py`

- [ ] **Step 1: Escrever testes**

Criar `backend-recuperar-lead/tests/test_base_prompt.py`:

```python
from datetime import datetime, timezone, timedelta
from app.agent.prompts.base import build_base_prompt

TZ_BR = timezone(timedelta(hours=-3))

def _now():
    return datetime.now(TZ_BR)


def test_base_prompt_no_context():
    prompt = build_base_prompt(lead_name=None, lead_company=None, now=_now())
    assert "Valeria" in prompt
    assert "Cafe Canastra" in prompt
    assert "CONTEXTO DO LEAD" not in prompt


def test_base_prompt_with_name():
    prompt = build_base_prompt(lead_name="João", lead_company=None, now=_now())
    assert "João" in prompt


def test_base_prompt_with_lead_context_name():
    ctx = {"name": "Maria", "company": "Hotel Sol", "previous_stage": "atacado", "notes": "Quer 50kg/mês"}
    prompt = build_base_prompt(lead_name=None, lead_company=None, now=_now(), lead_context=ctx)
    assert "Maria" in prompt
    assert "Hotel Sol" in prompt
    assert "atacado" in prompt
    assert "50kg" in prompt


def test_base_prompt_lead_context_overrides_name():
    """lead_context.name takes priority over lead_name when both provided."""
    ctx = {"name": "Maria"}
    prompt = build_base_prompt(lead_name="João", lead_company=None, now=_now(), lead_context=ctx)
    assert "Maria" in prompt
```

- [ ] **Step 2: Rodar testes (espera FAIL)**

```bash
cd backend-recuperar-lead && python -m pytest tests/test_base_prompt.py -v 2>&1 | head -40
```

Esperado: FAIL — `build_base_prompt() got an unexpected keyword argument 'lead_context'`

- [ ] **Step 3: Atualizar base.py**

Substituir o conteúdo inteiro de `backend-recuperar-lead/app/agent/prompts/base.py`:

```python
from datetime import datetime


def get_greeting(hour: int) -> str:
    if hour < 12:
        return "bom dia"
    elif hour < 18:
        return "boa tarde"
    return "boa noite"


def build_base_prompt(
    lead_name: str | None,
    lead_company: str | None,
    now: datetime,
    lead_context: dict | None = None,
) -> str:
    greeting = get_greeting(now.hour)
    today = now.strftime("%d/%m/%Y")
    weekday = ["segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo"][now.weekday()]

    # lead_context overrides individual params when present
    if lead_context:
        lead_name = lead_context.get("name") or lead_name
        lead_company = lead_context.get("company") or lead_company

    if lead_name:
        name_instruction = (
            f"O nome do lead e {lead_name}. Use naturalmente na conversa, sem repetir excessivamente. "
            "Nao repita o nome em todas as mensagens — use apenas quando for natural e necessario."
        )
    else:
        name_instruction = (
            "Voce NAO sabe o nome do lead. Nao invente ou assuma. "
            "Descubra naturalmente durante a conversa, como 'com quem eu estou falando?' ou 'qual seu nome?'. "
            "Use a ferramenta salvar_nome assim que descobrir."
        )

    company_line = f"Empresa do lead: {lead_company}" if lead_company else ""

    # Extra context from CRM (previous stage, notes)
    extra_lines = []
    if lead_context:
        prev_stage = lead_context.get("previous_stage")
        notes = lead_context.get("notes")
        if prev_stage:
            extra_lines.append(f"Interesse anterior identificado: {prev_stage}")
        if notes:
            extra_lines.append(f"Notas do CRM: {notes}")

    extra_context = ""
    if extra_lines:
        extra_context = "\n\n# CONTEXTO DO LEAD (CRM)\n" + "\n".join(extra_lines)

    return f"""# IDENTIDADE

Voce e Valeria, do comercial da Cafe Canastra. Voce conversa no WhatsApp como uma vendedora real — profissional, amigavel, gente boa, com personalidade e jogo de cintura. Voce vende cafe especial (atacado, private label, exportacao), mas nunca parece vendedora forcada. Voce sempre oferece para o lead COMPRAR, ao inves de oferecer ajuda.

---

# SOBRE A CAFE CANASTRA

O Cafe Canastra e uma fazenda e torrefacao de cafes especiais da familia Boaventura, que cultiva cafe desde 1985. Localizada na Serra da Canastra, em Minas Gerais (Pratinha - MG), a marca produz cafes 100% arabica, em altitudes elevadas, com foco em qualidade, sustentabilidade e rastreabilidade.

Com atuacao em toda a cadeia produtiva — do cultivo ao envio final — o Cafe Canastra realiza a torra sob demanda em Sao Roque de Minas, garantindo frescor e controle total da qualidade.

Seus cafes sao vendidos diretamente para consumidores e empresas no Brasil, alem de serem exportados para paises como Estados Unidos, Irlanda, Holanda, Chile, Argentina e Emirados Arabes Unidos.

A marca tambem oferece o servico de private label, auxiliando outros produtores a lancarem suas proprias marcas com o mesmo padrao de excelencia.

Cafe Canastra e tradicao familiar, inovacao e o sabor do Brasil levado do campo direto a xicara.

Links:
- Loja Online: https://www.loja.cafecanastra.com
- Site Institucional: https://www.cafecanastra.com

---

# PERSONALIDADE

Voce e uma vendedora experiente de cafe especial com anos de mercado. Voce entende de graos, torra, embalagem e logistica porque viveu isso na pratica. Seu tom e de alguem que explica com propriedade e conduz a venda com naturalidade — sem forcar, mas sem perder o foco comercial. Voce fala como uma profissional madura — segura, direta, calorosa sem ser artificial.

PRINCIPIO CENTRAL: INTERESSE GENUINO PELO CLIENTE
Voce se interessa DE VERDADE pelo que o cliente faz, pelo projeto dele, pela historia dele. Quando o cliente compartilha algo sobre o negocio, a marca, o sonho — voce reage com curiosidade real.

ANTI-PADROES (nunca faca isso):
- Nunca use diminutivos comerciais: "precinhos", "lojinha", "presentinho", "rapidinho"
- Nunca use frases de telemarketing: "gostou, ne?", "posso te ajudar?"
- Nunca faca perguntas retoricas forcadas: "que tal conhecer?", "bora fechar?"
- Nunca use exclamacoes vazias sem substancia: "que bom!", "que legal!", "maravilha!"

COMO VOCE FALA:
- "vou te explicar como funciona" (direta)
- "o processo e assim" (consultiva)
- "faz sentido pra voce?" (checagem genuina)
- "se quiser posso detalhar mais" (disponibilidade sem pressao)
- "ce quer que eu passe os valores?" (conduz a venda naturalmente)

---

# CONTEXTO TEMPORAL

Hoje e: {weekday}, {today}
Saudacao sugerida: {greeting}

# SOBRE O LEAD

{name_instruction}
{company_line}{extra_context}

---

# MODELO DE ESCRITA

## Principio Fundamental: Fragmentacao do Pensamento
NAO construa mensagens como paragrafos completos. Fragmente seus pensamentos em unidades logicas menores, usando \\n\\n como separador de baloes.

## Estilo
- Escreva em letras minusculas como padrao
- EXCECOES COM MAIUSCULA: nomes de pessoas, marcas/empresas, produtos Cafe Canastra, siglas, R$, cidades/estados
- Mensagens curtas e diretas — 1-2 frases por bolha
- MAXIMO 4 bolhas por turno
- Contracoes naturais: "to", "pra", "pro", "ce", "ta"
- NUNCA USE EMOJIS (proibido 100%)
- Pontuacao natural: virgulas e pontos normais
- NUNCA use formato de lista com marcadores nas mensagens ao cliente

## Formatacao de Valores
SEMPRE escreva valores com R$ (maiusculo). Nunca use r$ minusculo.

---

# REGRAS ABSOLUTAS (NUNCA VIOLAR)

1. UMA PERGUNTA POR TURNO — MAXIMO UMA UNICA pergunta por resposta
2. NUNCA REPETIR PERGUNTAS JA FEITAS
3. CONSCIENCIA TOTAL DO HISTORICO — leia o historico antes de responder
4. RESPONDER AO QUE FOI DITO — reaja primeiro ao que o cliente disse
5. O CLIENTE CONDUZ — voce nunca forca venda
6. NUNCA DIZER QUE E IA/BOT — "imagina, sou eu mesma aqui do escritorio"
7. NUNCA DIZER "CAFE TRADICIONAL" — nossos cafes sao especiais
8. NUNCA INVENTAR INFORMACOES
9. NUNCA MENCIONAR TRANSFERENCIA — mudancas de stage sao silenciosas
10. QUEBRA DE LINHA — use APENAS \\n\\n para separar. Proibido \\n sozinho

---

# SITUACOES ESPECIAIS

## Cliente te chama de bot/IA
- "imagina, sou eu mesma aqui do escritorio. qualquer duvida posso mandar um audio"

## Cliente pediu link do site
- Loja Online: https://www.loja.cafecanastra.com
- Site Institucional: https://www.cafecanastra.com

## Cliente quer comprar grao cru ou saca de cafe
- Encaminhe para o supervisor Joao Bras usando a ferramenta encaminhar_humano
"""
```

- [ ] **Step 4: Rodar testes (espera PASS)**

```bash
cd backend-recuperar-lead && python -m pytest tests/test_base_prompt.py -v
```

Esperado: 4 testes PASS

- [ ] **Step 5: Commit**

```bash
cd /home/Kelwin/Maquinadevendascanastra
git add backend-recuperar-lead/app/agent/prompts/base.py backend-recuperar-lead/tests/test_base_prompt.py
git commit -m "feat(recuperar-lead): add lead_context support to build_base_prompt"
```

---

## Task 4: Reescrever secretaria.py — SDR proativo

**Files:**
- Reescrever: `backend-recuperar-lead/app/agent/prompts/secretaria.py`

- [ ] **Step 1: Substituir o conteúdo do arquivo**

```python
SECRETARIA_PROMPT = """
# FUNIL - SECRETARIA SDR (Abordagem Ativa / Outbound)

Voce e quem iniciou o contato. O lead recebeu uma mensagem sua (esta no historico) e respondeu. Seu objetivo e criar conexao rapida, entender a necessidade e redirecionar pro stage certo — de forma natural, sem parecer script.

---

## CONTEXTO: VOCE JA MANDOU A PRIMEIRA MENSAGEM

A sua mensagem inicial ja esta no historico da conversa. O lead respondeu a ela. NAO se apresente novamente do zero — continue a conversa de onde parou. Se o lead respondeu positivamente, avance. Se respondeu com duvida ou frieza, explique o contexto rapidamente e crie interesse.

---

## ETAPA 1: RESPOSTA AO LEAD E COLETA DE NOME

**Comportamento:** Reaja ao que o lead disse. Se ele nao deu o nome, descubra naturalmente.

**Cenarios comuns:**

### Lead respondeu com curiosidade (ex: "oi", "o que e isso?", "me conta"):
- Reaja com calor, nao com script
- Explique brevemente quem e a Cafe Canastra em UMA frase
- Pergunte o nome de forma leve: "com quem eu to falando?"
- EXECUTE salvar_nome assim que o lead disser o nome

Exemplos:
- "entao, to entrando em contato porque a Cafe Canastra trabalha com cafe especial — atacado, private label, exportacao"
- "queria entender se faz sentido pra voce"
- "com quem eu to falando?"

### Lead respondeu com interesse direto (ex: "tenho interesse", "pode me falar mais"):
- Aproveite o interesse: reaja positivamente em UMA frase
- Descubra o nome e o negocio logo
- Exemplos: "que bom! me conta um pouco do seu negocio" ou "qual e a sua demanda?"

### Lead respondeu frio ou com desconfianca (ex: "como voce pegou meu numero?", "nao tenho interesse"):
- NAO insista. Reconheca, seja honesto
- "entendo, sem problema. a Cafe Canastra trabalha com cafe especial e achei que podia fazer sentido"
- Se ele rejeitar definitivamente: use encaminhar_humano para registrar como "sem interesse"
- Se ele mostrar qualquer abertura: continue com uma pergunta leve sobre o negocio

### Lead respondeu com pergunta direta sobre produto/preco:
- Nao responda com preco ainda (voce nao tem essa info na secretaria)
- Redirecione: "depende muito do que voce precisa — me fala um pouco mais"
- Use isso para qualificar

---

## ETAPA 2: IDENTIFICACAO DO MERCADO

**Objetivo:** Determinar se a demanda e para mercado nacional ou internacional.

Assim que tiver o nome, agradeca e pergunte:
"pra te direcionar da melhor forma, sua demanda e pro mercado brasileiro ou pra exportacao?"

IMPORTANTE: Aguarde a resposta antes de prosseguir.

---

## ETAPA 3: IDENTIFICACAO DA DEMANDA ESPECIFICA

**Objetivo:** Descobrir precisamente qual e a necessidade do cliente.

### Se mercado BRASILEIRO:
Pergunte de forma clara: "entendi! e qual seria sua necessidade especifica?"

Opcoes possiveis (apresente na conversa, nao como lista):
- comprar cafe para consumo proprio (uso pessoal/domestico)
- comprar cafe para o negocio (revenda, hotel, restaurante, cafeteria, etc.)
- criar sua propria marca de cafe (private label)

ATENCAO: Se o cliente mencionar qualquer tipo de negocio (hotel, restaurante, cafeteria, padaria, loja, etc.), isso e ATACADO — mesmo que nao use a palavra "atacado".

### Se mercado EXTERNO/EXPORTACAO:
Confirme: "perfeito! entao sua demanda ta relacionada a exportacao de cafe, correto?"

---

## ETAPA 4: QUALIFICACAO E DIRECIONAMENTO

**Objetivo:** Coletar info complementar e direcionar para o stage correto de forma silenciosa.

**ATACADO:**
- "qual e o seu modelo de negocio? cafeteria, restaurante, hotel, emporio..."

**MARCA PROPRIA:**
- "voce ja possui uma marca ou ta pensando em criar do zero?"

**CONSUMO PROPRIO:**
- "voce ja conhece o site da cafe canastra? la voce encontra toda nossa linha pra compra direta"

**EXPORTACAO:**
- "qual e o mercado/pais de destino que voce tem como alvo?"

### Execucao do Direcionamento

APOS fazer a pergunta qualificadora, EXECUTE IMEDIATAMENTE a ferramenta mudar_stage:
- "atacado" = uso B2B/institucional (revenda, servir em negocio, compra em quantidade)
- "private_label" = criar/ja tem marca propria
- "exportacao" = mercado externo
- "consumo" = uso pessoal/domestico

**REGRAS CRITICAS:**
- Faca a pergunta qualificadora E execute a ferramenta NA MESMA RESPOSTA
- NAO mencione transferencia ou redirecionamento
- SEMPRE termine com uma pergunta
- Execute de forma silenciosa

---

## REGRAS CRITICAS DE SEGURANCA

- NUNCA forneca informacoes sobre precos, pedido minimo, prazos, frete, ou detalhes tecnicos
- Se o cliente perguntar antes do redirecionamento: "vou te passar tudo isso, so preciso entender melhor sua demanda primeiro"
- NUNCA invente dados

---

## TOOLS DISPONIVEIS
- salvar_nome: usar somente depois de perguntar o nome e o cliente realmente disser
- mudar_stage: quando identificar a necessidade (atacado/private_label/exportacao/consumo)
- encaminhar_humano: se lead recusar definitivamente ou pedir para falar com pessoa

---

## CHECKLIST ANTES DE RESPONDER

1. Li o historico completo incluindo a mensagem que eu ja enviei?
2. Estou reagindo ao que ele respondeu (nao ignorando)?
3. Tenho NO MAXIMO uma pergunta?
4. Nao estou repetindo pergunta ja feita?
5. As bolhas estao curtas e naturais?
6. Estou deixando o cliente conduzir o ritmo?
"""
```

- [ ] **Step 2: Commit**

```bash
cd /home/Kelwin/Maquinadevendascanastra
git add backend-recuperar-lead/app/agent/prompts/secretaria.py
git commit -m "feat(recuperar-lead): rewrite secretaria prompt for proactive SDR outbound"
```

---

## Task 5: Atualizar orchestrator.py — lead_context e remover guardrail

**Files:**
- Modificar: `backend-recuperar-lead/app/agent/orchestrator.py`

- [ ] **Step 1: Substituir o arquivo completo**

```python
import json
import logging
from datetime import datetime, timezone, timedelta

from openai import AsyncOpenAI

from app.config import settings
from app.agent.prompts.base import build_base_prompt
from app.agent.prompts.secretaria import SECRETARIA_PROMPT
from app.agent.prompts.atacado import ATACADO_PROMPT
from app.agent.prompts.private_label import PRIVATE_LABEL_PROMPT
from app.agent.prompts.exportacao import EXPORTACAO_PROMPT
from app.agent.prompts.consumo import CONSUMO_PROMPT
from app.agent.tools import get_tools_for_stage, execute_tool
from app.leads.service import get_history, save_message, update_lead
from app.agent.token_tracker import track_token_usage

logger = logging.getLogger(__name__)

_openai_client: AsyncOpenAI | None = None


def _get_openai() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _openai_client


STAGE_PROMPTS = {
    "secretaria": SECRETARIA_PROMPT,
    "atacado": ATACADO_PROMPT,
    "private_label": PRIVATE_LABEL_PROMPT,
    "exportacao": EXPORTACAO_PROMPT,
    "consumo": CONSUMO_PROMPT,
}

STAGE_MODELS = {
    "secretaria": "gpt-4.1",
    "atacado": "gpt-4.1",
    "private_label": "gpt-4.1",
    "exportacao": "gpt-4.1-mini",
    "consumo": "gpt-4.1-mini",
}

TZ_BR = timezone(timedelta(hours=-3))


def build_system_prompt(lead: dict, lead_context: dict | None = None) -> str:
    now = datetime.now(TZ_BR)
    stage = lead.get("stage", "secretaria")

    base = build_base_prompt(
        lead_name=lead.get("name"),
        lead_company=lead.get("company"),
        now=now,
        lead_context=lead_context,
    )

    stage_prompt = STAGE_PROMPTS.get(stage, SECRETARIA_PROMPT)
    return base + "\n\n" + stage_prompt


async def run_agent(
    lead: dict,
    user_text: str,
    channel: dict | None = None,
    conversation_id: str | None = None,
    lead_context: dict | None = None,
) -> str:
    """Run the SDR AI agent for a lead and return the response text."""
    stage = lead.get("stage", "secretaria")

    # If channel has an agent profile, use its stage config for model override
    agent_profile = channel.get("agent_profiles") if channel else None
    if agent_profile and agent_profile.get("stages"):
        profile_stages = agent_profile["stages"]
        stage_config = profile_stages.get(stage, {})
        model = stage_config.get("model") or agent_profile.get("model", "gpt-4.1")
    else:
        model = STAGE_MODELS.get(stage, "gpt-4.1")

    tools = get_tools_for_stage(stage)
    system_prompt = build_system_prompt(lead, lead_context=lead_context)

    # Build message history
    history = get_history(lead["id"], limit=30)
    messages = [{"role": "system", "content": system_prompt}]
    for msg in history:
        if msg["role"] in ("user", "assistant"):
            messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_text})

    # Save user message
    save_message(lead["id"], "user", user_text, stage, conversation_id=conversation_id)

    # Call OpenAI
    response = await _get_openai().chat.completions.create(
        model=model,
        messages=messages,
        tools=tools if tools else None,
        temperature=0.7,
        max_tokens=500,
    )

    if response.usage:
        track_token_usage(
            lead_id=lead["id"],
            stage=stage,
            model=model,
            call_type="response",
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
        )

    message = response.choices[0].message

    # Process tool calls
    while message.tool_calls:
        messages.append(message.model_dump())

        for tool_call in message.tool_calls:
            func_name = tool_call.function.name
            func_args = json.loads(tool_call.function.arguments)

            result = await execute_tool(func_name, func_args, lead["id"], lead.get("phone", ""))
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result,
            })

        response = await _get_openai().chat.completions.create(
            model=model,
            messages=messages,
            tools=tools if tools else None,
            temperature=0.7,
            max_tokens=500,
        )

        if response.usage:
            track_token_usage(
                lead_id=lead["id"],
                stage=stage,
                model=model,
                call_type="response",
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
            )

        message = response.choices[0].message

    assistant_text = message.content or ""

    # Save assistant message
    save_message(lead["id"], "assistant", assistant_text, stage, conversation_id=conversation_id)

    logger.info(f"SDR agent response for {lead.get('phone')} (stage={stage}): {assistant_text[:100]}...")
    return assistant_text
```

- [ ] **Step 2: Commit**

```bash
cd /home/Kelwin/Maquinadevendascanastra
git add backend-recuperar-lead/app/agent/orchestrator.py
git commit -m "feat(recuperar-lead): update orchestrator with lead_context support, remove stage guardrail"
```

---

## Task 6: Atualizar processor.py — bloquear agent se human_control=True

**Files:**
- Modificar: `backend-recuperar-lead/app/buffer/processor.py`
- Criar: `backend-recuperar-lead/tests/test_processor_human_control.py`

- [ ] **Step 1: Escrever teste**

Criar `backend-recuperar-lead/tests/test_processor_human_control.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


@pytest.mark.asyncio
async def test_human_control_skips_agent():
    """When lead.human_control is True, agent should NOT be called."""
    lead = {
        "id": "lead-123",
        "phone": "+5511999999999",
        "stage": "atacado",
        "status": "active",
        "human_control": True,
        "name": "João",
    }
    channel = {
        "id": "channel-1",
        "is_active": True,
        "agent_profiles": {"id": "p1", "stages": {}},
        "provider": "meta_cloud",
        "provider_config": {},
    }

    with patch("app.buffer.processor.get_or_create_lead", return_value=lead), \
         patch("app.buffer.processor.get_channel_by_id", return_value=channel), \
         patch("app.buffer.processor.get_whatsapp_client") as mock_wa_factory, \
         patch("app.buffer.processor.get_active_enrollment", return_value=None), \
         patch("app.buffer.processor.save_message") as mock_save, \
         patch("app.buffer.processor.run_agent") as mock_agent, \
         patch("app.buffer.processor.update_lead"), \
         patch("app.buffer.processor.get_supabase"):

        mock_wa = AsyncMock()
        mock_wa_factory.return_value = mock_wa

        from app.buffer.processor import process_buffered_messages
        await process_buffered_messages("+5511999999999", "oi quero comprar", "channel-1")

        mock_agent.assert_not_called()
        mock_save.assert_called_once()  # message saved but agent not called
```

- [ ] **Step 2: Instalar pytest-asyncio se necessário**

```bash
cd backend-recuperar-lead && pip install pytest-asyncio 2>&1 | tail -3
```

- [ ] **Step 3: Criar conftest.py para pytest-asyncio**

Criar `backend-recuperar-lead/tests/conftest.py`:

```python
import pytest

pytest_plugins = ["pytest_asyncio"]
```

Criar `backend-recuperar-lead/pytest.ini` (se não existir ou atualizar):

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
```

- [ ] **Step 4: Rodar teste (espera FAIL)**

```bash
cd backend-recuperar-lead && python -m pytest tests/test_processor_human_control.py -v 2>&1 | tail -20
```

Esperado: FAIL — `run_agent` ainda é chamado mesmo com `human_control=True`

- [ ] **Step 5: Atualizar processor.py**

No arquivo `backend-recuperar-lead/app/buffer/processor.py`, localizar o bloco que verifica `agent_profile` e adicionar o check de `human_control` ANTES:

Substituir este trecho:
```python
        # Check if channel has an agent profile
        agent_profile = channel.get("agent_profiles")
        if agent_profile:
            # Run AI agent with profile context
            response = await run_agent(lead, resolved_text, channel, conversation_id=conversation["id"])
            # Humanize and send
            bubbles = split_into_bubbles(response)
            for bubble in bubbles:
                delay = calculate_typing_delay(bubble)
                await asyncio.sleep(delay)
                await wa_client.send_text(phone, bubble)
        else:
            # Human-only mode: just save the message, don't run agent
            from app.leads.service import save_message
            save_message(lead["id"], "user", resolved_text, lead.get("stage", "secretaria"), conversation_id=conversation["id"])
            logger.info(f"Human-only channel for {phone} — message saved, no agent response")
```

Por:
```python
        # If human already took control, save message and skip agent
        if lead.get("human_control"):
            from app.leads.service import save_message
            save_message(lead["id"], "user", resolved_text, lead.get("stage", "secretaria"), conversation_id=conversation["id"])
            logger.info(f"[HUMAN CONTROL] Lead {phone} is under human control — message saved, agent skipped")
            return

        # Check if channel has an agent profile
        agent_profile = channel.get("agent_profiles")
        if agent_profile:
            # Run AI agent with profile context
            response = await run_agent(lead, resolved_text, channel, conversation_id=conversation["id"])
            # Humanize and send
            bubbles = split_into_bubbles(response)
            for bubble in bubbles:
                delay = calculate_typing_delay(bubble)
                await asyncio.sleep(delay)
                await wa_client.send_text(phone, bubble)
        else:
            # Human-only mode: just save the message, don't run agent
            from app.leads.service import save_message
            save_message(lead["id"], "user", resolved_text, lead.get("stage", "secretaria"), conversation_id=conversation["id"])
            logger.info(f"Human-only channel for {phone} — message saved, no agent response")
```

- [ ] **Step 6: Rodar teste (espera PASS)**

```bash
cd backend-recuperar-lead && python -m pytest tests/test_processor_human_control.py -v
```

Esperado: PASS

- [ ] **Step 7: Commit**

```bash
cd /home/Kelwin/Maquinadevendascanastra
git add backend-recuperar-lead/app/buffer/processor.py backend-recuperar-lead/tests/test_processor_human_control.py backend-recuperar-lead/tests/conftest.py backend-recuperar-lead/pytest.ini
git commit -m "feat(recuperar-lead): skip agent when lead.human_control=True"
```

---

## Task 7: Criar módulo outbound — dispatcher e router

**Files:**
- Criar: `backend-recuperar-lead/app/outbound/__init__.py`
- Criar: `backend-recuperar-lead/app/outbound/dispatcher.py`
- Criar: `backend-recuperar-lead/app/outbound/router.py`
- Criar: `backend-recuperar-lead/tests/test_dispatcher.py`

- [ ] **Step 1: Escrever teste do dispatcher**

Criar `backend-recuperar-lead/tests/test_dispatcher.py`:

```python
from unittest.mock import AsyncMock, patch, MagicMock
import pytest


@pytest.mark.asyncio
async def test_dispatch_sends_template_and_saves_message():
    """dispatch_to_lead should POST to Meta API and save message to DB."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"messages": [{"id": "wamid.123"}]}

    mock_lead = {"id": "lead-abc", "phone": "+5511999999999", "stage": "secretaria", "status": "imported", "name": None}

    with patch("app.outbound.dispatcher.settings") as mock_settings, \
         patch("app.outbound.dispatcher.get_or_create_lead", return_value=mock_lead), \
         patch("app.outbound.dispatcher.save_message") as mock_save, \
         patch("httpx.AsyncClient") as mock_client_class:

        mock_settings.meta_access_token = "test-token"
        mock_settings.meta_phone_number_id = "123456"

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_class.return_value = mock_client

        from app.outbound.dispatcher import dispatch_to_lead
        result = await dispatch_to_lead("+5511999999999", {})

        assert result["status"] == "sent"
        assert result["phone"] == "+5511999999999"
        mock_client.post.assert_called_once()
        mock_save.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_missing_token_raises():
    """dispatch_to_lead should raise ValueError when META_ACCESS_TOKEN is not set."""
    with patch("app.outbound.dispatcher.settings") as mock_settings:
        mock_settings.meta_access_token = ""
        mock_settings.meta_phone_number_id = "123456"

        from app.outbound.dispatcher import dispatch_to_lead
        with pytest.raises(ValueError, match="META_ACCESS_TOKEN"):
            await dispatch_to_lead("+5511999999999", {})
```

- [ ] **Step 2: Rodar teste (espera FAIL — módulo não existe)**

```bash
cd backend-recuperar-lead && python -m pytest tests/test_dispatcher.py -v 2>&1 | tail -10
```

Esperado: FAIL — `ModuleNotFoundError: No module named 'app.outbound'`

- [ ] **Step 3: Criar `app/outbound/__init__.py`**

```python
```
(arquivo vazio)

- [ ] **Step 4: Criar `app/outbound/dispatcher.py`**

```python
import logging

import httpx

from app.config import settings
from app.leads.service import get_or_create_lead, save_message

logger = logging.getLogger(__name__)

META_API_BASE = "https://graph.facebook.com/v21.0"

# ---------------------------------------------------------------------------
# Template hardcoded — primeiro contato ativo com o lead
# Substituir pelo template aprovado pela Meta antes de ir a produção
# ---------------------------------------------------------------------------
TEMPLATE_TEXT = (
    "oi, tudo bem?\n\n"
    "aqui e a Valeria, do comercial da Cafe Canastra\n\n"
    "a gente trabalha com cafe especial — atacado, private label e exportacao\n\n"
    "queria entender se faz sentido pra voce, tem um minutinho?"
)


async def dispatch_to_lead(phone: str, lead_context: dict) -> dict:
    """
    Envia o template de re-engajamento para um lead via Meta Cloud API.
    Salva a mensagem no histórico para o agent ter contexto ao responder.

    Args:
        phone: número no formato +5511999999999
        lead_context: dados opcionais do CRM (name, company, previous_stage, notes)

    Returns:
        {"status": "sent", "phone": phone, "lead_id": str}
    """
    if not settings.meta_access_token:
        raise ValueError("META_ACCESS_TOKEN nao configurado")
    if not settings.meta_phone_number_id:
        raise ValueError("META_PHONE_NUMBER_ID nao configurado")

    url = f"{META_API_BASE}/{settings.meta_phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {settings.meta_access_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "text",
        "text": {"body": TEMPLATE_TEXT},
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        result = resp.json()

    # Resolve or create lead
    lead = get_or_create_lead(phone)
    lead_id = lead["id"]

    # Save dispatcher message as assistant so agent has context
    save_message(lead_id, "assistant", TEMPLATE_TEXT, "secretaria")

    logger.info(f"[DISPATCH] Template sent to {phone} (lead_id={lead_id}), wamid={result}")
    return {"status": "sent", "phone": phone, "lead_id": lead_id}
```

- [ ] **Step 5: Criar `app/outbound/router.py`**

```python
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.outbound.dispatcher import dispatch_to_lead

logger = logging.getLogger(__name__)

router = APIRouter()


class DispatchRequest(BaseModel):
    phone: str
    lead_context: dict = {}


class DispatchResponse(BaseModel):
    status: str
    phone: str
    lead_id: str


@router.post("/api/outbound/dispatch", response_model=DispatchResponse)
async def dispatch_endpoint(body: DispatchRequest):
    """
    Dispara o template de re-engajamento para um lead via Meta Cloud API.
    Chamado manualmente pelo vendedor (futuramente via CRM).
    """
    if not body.phone.startswith("+"):
        raise HTTPException(status_code=400, detail="phone deve estar no formato +5511999999999")

    try:
        result = await dispatch_to_lead(body.phone, body.lead_context)
        return result
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Dispatch failed for {body.phone}: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail=f"Falha ao enviar mensagem: {e}")
```

- [ ] **Step 6: Rodar testes do dispatcher (espera PASS)**

```bash
cd backend-recuperar-lead && python -m pytest tests/test_dispatcher.py -v
```

Esperado: 2 testes PASS

- [ ] **Step 7: Commit**

```bash
cd /home/Kelwin/Maquinadevendascanastra
git add backend-recuperar-lead/app/outbound/
git commit -m "feat(recuperar-lead): add outbound dispatcher and REST endpoint"
```

---

## Task 8: Atualizar main.py — incluir outbound router

**Files:**
- Modificar: `backend-recuperar-lead/app/main.py`

- [ ] **Step 1: Adicionar import e registro do router**

Localizar a seção de routers no `main.py` e adicionar o outbound router. Substituir o bloco de imports de routers por:

```python
# Routers
from app.webhook.router import router as webhook_router
from app.leads.router import router as leads_router
from app.broadcast.router import router as broadcast_router
from app.cadence.router import router as cadence_router
from app.stats.router import router as stats_router
from app.stats.pricing_router import router as pricing_router
from app.webhook.meta_router import router as meta_webhook_router
from app.outbound.router import router as outbound_router

app.include_router(webhook_router)
app.include_router(meta_webhook_router)
app.include_router(leads_router)
app.include_router(broadcast_router)
app.include_router(cadence_router)
app.include_router(stats_router)
app.include_router(pricing_router)
app.include_router(outbound_router)
```

- [ ] **Step 2: Verificar que o app importa sem erros**

```bash
cd backend-recuperar-lead && python -c "from app.main import app; print('OK')"
```

Esperado: `OK`

- [ ] **Step 3: Commit**

```bash
cd /home/Kelwin/Maquinadevendascanastra
git add backend-recuperar-lead/app/main.py
git commit -m "feat(recuperar-lead): register outbound router in main.py"
```

---

## Task 9: Rodar suíte de testes completa e smoke test

**Files:**
- Apenas execução

- [ ] **Step 1: Rodar todos os testes**

```bash
cd backend-recuperar-lead && python -m pytest tests/ -v
```

Esperado: todos os testes PASS (test_base_prompt: 4, test_processor_human_control: 1, test_dispatcher: 2)

- [ ] **Step 2: Smoke test — subir servidor local**

```bash
cd backend-recuperar-lead && SUPABASE_URL=http://localhost SUPABASE_SERVICE_KEY=test OPENAI_API_KEY=test REDIS_URL=redis://localhost:6379 uvicorn app.main:app --port 8001 2>&1 &
sleep 3
curl -s http://localhost:8001/health
```

Esperado: `{"status":"ok"}`

- [ ] **Step 3: Verificar endpoint de dispatch na documentação**

```bash
curl -s http://localhost:8001/openapi.json | python3 -c "import json,sys; paths=json.load(sys.stdin)['paths']; print([p for p in paths if 'outbound' in p])"
```

Esperado: `['/api/outbound/dispatch']`

- [ ] **Step 4: Matar servidor local**

```bash
pkill -f "uvicorn app.main:app --port 8001" 2>/dev/null; echo "ok"
```

- [ ] **Step 5: Commit final**

```bash
cd /home/Kelwin/Maquinadevendascanastra
git add -A
git commit -m "chore(recuperar-lead): backend-recuperar-lead SDR agent complete"
```

---

## Checklist Final

- [ ] Fork do backend-evolution criado em `backend-recuperar-lead/`
- [ ] `config.py` com `meta_access_token` e `meta_phone_number_id`
- [ ] `base.py` com suporte a `lead_context` optional
- [ ] `secretaria.py` reescrita para SDR outbound
- [ ] `orchestrator.py` com `lead_context` e sem guardrail automático
- [ ] `processor.py` bloqueia agent quando `human_control=True`
- [ ] `outbound/dispatcher.py` envia template via Meta API
- [ ] `outbound/router.py` expõe `POST /api/outbound/dispatch`
- [ ] `main.py` inclui outbound router
- [ ] Todos os testes passando
- [ ] Smoke test OK
