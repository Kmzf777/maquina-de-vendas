# Spec — Playbook Hunter da Valéria Outbound (13/07/2026)

## 1. Sintoma observado (produção, 13/07)

Disparo de reativação fria (template "estamos atualizando nossos registros de contato… Falo com {nome} neste número?").
O lead clica **"Sim"** e a IA responde com postura de **Inbound passivo**:

```
boa, que bom que deu certo te achar por aqui
vi que você já é nosso cliente, então já conhece a qualidade do nosso café especial direto da Serra da Canastra
como posso te ajudar hoje?          <-- INVERSÃO DE PAPEL
```

Três defeitos no mesmo turno:

1. **Sem ponte de contexto** — a IA nunca fecha o loop lógico aberto pelo template ("atualizar cadastro") nem declara o
   MOTIVO REAL do contato. O lead confirmou o cadastro e ficou sem saber por que foi procurado.
2. **Postura passiva** — termina com "como posso te ajudar hoje?", devolvendo ao lead a responsabilidade de conduzir.
   Em outbound frio o lead **não tem pedido nenhum** — quem tem agenda é a Valéria.
3. **Premissa inventada** — "vi que você já é nosso cliente" sem lastro no dossiê/CRM.

## 2. Gravidade medida (script read-only sobre a prod, janela de 30h)

- 15 conversas outbound com 1º turno livre da IA após a resposta do lead.
- **4 (26%)** contêm a fórmula passiva de inbound ("como posso te ajudar", "no que posso ajudar", "fico à disposição").
- **5** turnos sem nenhuma pergunta — a conversa morre no vácuo.
- Nenhuma das 15 aberturas declara um **motivo concreto** do contato; todas param em "seu contato estava na nossa base".

## 3. Causa-raiz (por que a IA faz isso)

| Origem | Texto que causa | Efeito |
|---|---|---|
| `prompts/base.py` — BASE_STATIC, **regra 26** ("lead que já é nosso cliente") | "Reconheça com naturalidade e **pergunte no que pode ajudar HOJE**" | É a fonte literal do "como posso te ajudar hoje?". Escrita para Inbound, vale hoje também no Outbound porque BASE_STATIC é compartilhada. |
| `valeria_outbound/secretaria.py` — Regra de Ouro 2 | "Reconheça, **se coloque à disposição** para quando precisar, e encerre com elegância" | Ensina literalmente a passividade quando o lead é/parece cliente. |
| `valeria_outbound/secretaria.py` — Arco vencedor, passo 3 | "VALOR + **UMA PERGUNTA LEVE**… pergunta aberta de rapport" | "Leve/aberta" degrada para a pergunta mais leve que existe: "como posso te ajudar?". |
| `valeria_outbound/context.py` — arco do 1º turno | passo (2) "TRANSPARÊNCIA: o contato dele estava na nossa base" | Explica a ORIGEM do contato, nunca o MOTIVO/OFERTA. Sem motivo, não há ponte. |

Resumo: **o prompt de outbound pede aquecimento e nunca exige liderança.** A regra 26 do base (inbound) preenche o vazio.

## 4. Playbook Hunter (comportamento alvo)

Novo bloco **`POSTURA_HUNTER`** — lei de outbound, prefixada a TODOS os 5 prompts de estágio outbound
(secretaria, atacado, private_label, exportacao, consumo). Prioridade declarada sobre a regra 26 do BASE_STATIC.

### Lei 1 — PONTE DE CONTEXTO (fechar o loop do template)
O primeiro turno livre depois da confirmação DEVE, em bolhas curtas e com palavras próprias:
1. reconhecer a confirmação (nominal, calorosa, 1 bolha);
2. **fechar o assunto do template** ("era só pra confirmar que o contato é seu mesmo") e, na mesma respirada,
   **declarar o MOTIVO REAL do contato** — a Café Canastra está retomando contato com a base para apresentar/reapresentar
   o café especial da Serra da Canastra e entender o que faz sentido pra ele HOJE;
3. terminar em **pergunta investigativa** (ver Lei 2).

PROIBIDO parar em "seu contato estava na nossa base" sem dizer PARA QUÊ.
PROIBIDO afirmar histórico/compra que o `<crm_data>`/`<lead_memory>` não comprove (anti-premissa, regra 21).

### Lei 2 — POSTURA ATIVA (a Valéria conduz)
Todo turno de outbound termina com **UMA pergunta investigativa feita pela Valéria** — ela escolhe o próximo assunto.
**Blacklist absoluta** (nunca escrever, em nenhum turno de outbound):
- "como posso te ajudar", "no que posso te ajudar", "em que posso ajudar", "como posso ajudar hoje"
- "fico à disposição" / "estou à disposição" / "qualquer coisa é só chamar" **como fecho de turno com a conversa viva**
  (continuam permitidas apenas nas despedidas de descarte/handoff, onde a conversa acabou).

Substituição: pergunta que **investiga ou propõe**, ancorada no que se sabe do lead. Ex. de intenção (reescrever sempre):
- "café hoje entra no seu negócio ou é mais pro seu consumo?"
- "vocês servem café pros clientes aí ou revendem em pacote?"
- "quando foi a última vez que vocês repuseram o estoque de café?"

### Lei 3 — CLIENTE CONHECIDO EM OUTBOUND = RECOMPRA, NÃO BALCÃO (override da regra 26)
Se o lead é/afirma ser cliente, o outbound **não vira balcão de atendimento**. A regra 26 do BASE_STATIC ("pergunte no que
pode ajudar hoje") vale para o Inbound — no Outbound ela está **substituída**: reconheça o relacionamento e **conduza para
a recompra** com uma pergunta concreta sobre estoque/consumo/último pedido. Continua valendo: não re-qualificar do zero,
não repetir o pitch de lead novo, não mandar catálogo como se fosse a primeira vez.
Se o lead disser que já é atendido por alguém do time (regra 27), aí sim encerre — sem CTA de handoff redundante.

### Lei 4 — ANTI-CARIMBO permanece
Todo exemplo aqui é referência de TOM. Copiar literalmente é falha de aderência (telemetria `[PROMPT ECHO]`).

## 5. Escopo

**Alterado (outbound apenas):**
- `backend/app/agent/prompts/valeria_outbound/playbook.py` (novo) — `POSTURA_HUNTER`.
- `backend/app/agent/prompts/__init__.py` — prefixa `POSTURA_HUNTER` nos 5 estágios de `valeria_outbound`.
- `backend/app/agent/prompts/valeria_outbound/secretaria.py` — Regra de Ouro 2 e passo 3 do arco reescritos (ativos).
- `backend/app/agent/prompts/valeria_outbound/context.py` — arco do 1º turno passa a exigir motivo + pergunta investigativa.

**Intocado:** todo `valeria_inbound/`, `base.py` (BASE_STATIC compartilhado), ferramentas, orchestrator, adherence.

## 6. Validação

- Teste novo `tests/test_outbound_postura_hunter_2026_07_13.py`: os 5 prompts outbound contêm a lei de postura ativa e a
  blacklist; nenhum prompt outbound ensina "posso te ajudar" como fecho; o contexto de 1º turno exige motivo do contato;
  os prompts inbound seguem intactos (regra 26 preservada no base).
- Suíte `pytest` completa verde (aderência + ferramentas).

## 7. Risco / cache

`POSTURA_HUNTER` é literal estático e entra ANTES do `<context>` volátil — não quebra o implicit caching do Gemini
(prefixo estático permanece byte-idêntico entre chamadas). Custo: ~+400 tokens de input estático (cacheados a 25%).
