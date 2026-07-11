# Auditoria Geral — Atendimentos da Valéria (11/07/2026)

**Janela:** últimas 24h (≈ 10/07 19h UTC → 11/07 19h UTC).
**Escopo:** todos os canais inbound ativos. **Excluídos por diretriz:** leads `5567981382707` e `5511987506497` (e variantes sem o 9º dígito), filtrados no SQL de extração.
**Método:** script temporário read-only (`scripts/temp_audit_valeria_geral.py`, removido após o uso) via Management API — somente `SELECT`. Leitura integral de 100% dos transcritos (38 conversas / 26 leads / 628 mensagens), cruzada com `token_usage`, `delivery_status`, latência por turno e horários dos deploys de hoje (R2 handoff-responde-antes 11:05 BRT, R3 guardas do "?" 12:12 BRT, ponte com filtro de intenção 12:50 BRT).

## Volumetria e saúde sistêmica

- 38 conversas com atividade / 26 leads únicos / 628 mensagens. 100% inbound (0 outbound na janela).
- **Zero ghosting com IA ligada:** todos os inbounds com `ai_enabled=true` foram respondidos em 3–56s (p50 ≈ 30s).
- **Entrega 100%:** nenhuma mensagem com `delivery_status=failed`; maioria `read`.
- **Zero vazamento de `tool_code`, zero resposta vazia, zero duplicata de conteúdo, zero loop de retry.**
- **Zero alucinação de catálogo detectada:** preços citados (R$25,70/26,70 250g, R$47,70/48,70 500g, R$29,70 microlote, R$97,70 kg em grãos, Kit Amostra R$60) e o "Néctar de Minas Gourmet 500g R$39,70 / 75 SCA" conferem com o catálogo documentado.
- 13 dos 26 leads terminaram a janela com a última mensagem deles sem resposta — **todos os 13 em estado pós-handoff (IA desligada)**. Nenhum caso é falha da IA em responder; ver Categoria 3.

---

## Categoria 1 — Erros Sistêmicos (bugs vivos no código atual)

### S1. Handoff DUPLICADO: guarda determinística não é idempotente com tool-call no mesmo turno — **bug vivo pós-deploy**
**Caso:** Professor Sebastião Alves (lead de **500kg–1t/mês**), 15:29 BRT (após todos os deploys de hoje).
Sequência em 21 segundos: `encaminhar_humano` via tool-call (15:29:13) → bolha de despedida + **cartão do João nº 1** (15:29:20) → a resposta do LLM também verbalizava handoff → a **guarda "handoff verbalizado sem tool-call"** disparou de novo (15:29:28) → segunda despedida de 5 parágrafos + **cartão nº 2** (15:29:34). Dois minutos depois, a ponte reenviou o **cartão nº 3**. O lead recebeu 3 cartões e 2 despedidas quase idênticas em 2 minutos e terminou a conversa com um "?" que ficou sem qualquer resposta. A guarda precisa saber que um handoff por tool-call já executou no mesmo turno.

### S2. Ponte pós-handoff engole pergunta de PREÇO — **reproduzido após o deploy do filtro de intenção (12:50 BRT)**
O filtro da ponte só distingue "despedida social" (reage ❤️ — funcionou: caso Mateus 14:27 BRT) de "resto" (carimbo `seu atendimento tá com o João agora…` + reenvio de cartão). Pergunta substantiva cai no carimbo:
- **Mateus 14:27 BRT:** "Qual o valor da unidade" → carimbo. (Ironia: a dúvida dele era exatamente preço, e o handoff tinha acontecido por causa do lote mínimo.)
- **Leonardo José 14:44 BRT:** "gostaria de saber o valor das sacas no grão" → carimbo. Ele repetiu a pergunta no número do João às 14:46 e segue sem resposta.
- Pré-deploy, mesmo padrão: Geraldo ("vocês são de qual região?"), Blue Sky (lista completa de specs MOQ/FBA → carimbo de 131 chars).
- Variante tom-surdo: Sebastião disse "**Mandei mensagem pra ele, estou aguardando**" e a ponte respondeu "se preferir, chama ele direto no contato…" — como se ele não tivesse chamado. Resposta dele: "?".

### S3. Fallback "me embolei aqui por um instante" descarta o conteúdo do turno do lead
**Caso café caseiro, 07:05 BRT:** áudio perguntando o custo unitário da embalagem personalizada (logo + número + Pix) → a IA respondeu "opa, me embolei aqui por um instante / quer que eu siga com o próximo passo…?". A pergunta nunca foi respondida; na sequência veio o handoff. O mecanismo de recuperação salva a conversa, mas joga fora a pergunta que causou o tropeço.

### S4 (menor). Corrida texto×mídia: "enviei aqui as fotos" chega segundos ANTES das fotos
Recorrente (Gustavo, Janaina, Charleston, Sebastião): a bolha afirma que as fotos já foram enviadas 8–17s antes de `enviar_fotos` completar. Cosmético na maioria dos casos, mas com lead rápido gera confusão de referência ("Essa" apontando para foto que ainda não chegou).

---

## Categoria 2 — Falhas de Conversão (prompt/comportamento)

### C1. Handoff engolindo pergunta de preço/MOQ — 4 casos, todos ANTES do fix R2 (11:05 BRT); 0 casos depois
- **Elias Félix 06:23 BRT:** "vê o que tem melhor de preço nesse de 500g" → cartão sem preço.
- **Lead 5534996510611 07:42 BRT:** "Qual o pedido mínimo? E posso mesclar embalagens?" → cartão sem resposta.
- **ALEMÃO AGROINDÚSTRIA 08:19 BRT:** "gostaria de conhecer os detalhes da sua empresa e PREÇOS" → cartão sem preço. Repetiu "PREÇOS" no número do João às 09:01 e segue no vácuo.
- **Consultora Janaina 11:07 BRT** (na virada do deploy): a IA ofereceu "quer que eu te passe o valor do microlote?", o lead disse "Sim sim" → cartão **sem o preço prometido**.

Pós-deploy o padrão inverteu: Geraldo, Tião, Mateus, Mazinho e Sebastião receberam preço/resposta ANTES da despedida. **O fix R2 aparenta efetivo no turno de handoff; o vazamento restante migrou para a ponte (S2).**

### C2. Objeção de preço morre no vácuo pós-handoff
- **Tião da Silva 13:50 BRT:** "tá saindo mais caro do que no supermercado" — objeção clássica, IA já desligada, sem tratamento e sem humano. Lead de mercadinho perdido por silêncio.
- **Mayckel Willyan (10/07 noite):** objeção de preço/praça verbalizada em áudio → handoff correto, mas a objeção ficou esperando humano (boa escuta ativa antes: a sondagem "ficou alguma dúvida sobre pedido mínimo, prazo ou preço?" extraiu a objeção real).
- **Mazinho Venial 08:10 BRT:** só queria orçamento **das embalagens avulsas** (não vendemos) — recebeu cartão do João em vez de um "não trabalhamos com embalagem avulsa" direto; despediu-se educadamente e saiu. Handoff desnecessário na fila do João.

### C3. Misqualificação: representante comercial encaminhado como "private label qualificado"
**Nilson Gaspar (10/07 20:04 BRT):** declarou duas vezes ser **representante** (quer representar, não comprar). Stage oscilou private_label→atacado→private_label em 3 min; a IA insistiu no pitch de PL, enviou fotos e fez handoff qualificado com base em "👏👏👏👏" e "SIM aaaaaaaaa" de cortesia. Ruído na fila do João; o roteiro não tem saída para "representante".

### C4. Lead internacional de alto potencial mal servido (Blue Sky Consultancy, Portugal → Amazon EUA)
Perguntou **duas vezes** "vocês já exportam para os EUA? documentação de exportação?" — nunca respondido. MOQ primeiro adiado ("o João te confirma no fechamento"), depois respondido. Handoff **"por tempo"** cortou a conversa no meio do engajamento; a mensagem seguinte (specs completas: 340g/12oz, válvula, zíper, FBA) bateu no carimbo da ponte (S2) e depois no vácuo do João. É o lead mais estruturado do dia e o atendimento terminou em 3 mensagens dele sem interlocutor.

---

## Categoria 3 — Drop-offs / Vácuo humano (operacional, NÃO é bug de IA)

**A causa dominante de abandono hoje segue sendo a sala de espera do humano** (reincidência do achado de ontem):

11 leads tocaram o cartão e chamaram o número do João **sem nenhuma resposta humana dentro da janela** — a maioria em horário comercial de sexta-feira:

| Lead | Chamou o João (BRT) | Conteúdo |
|---|---|---|
| Elias Félix | 06:39 | Apresentação completa + "quero o 500g com minha marca" |
| 5534996510611 | 07:44 | "A Valéria pediu que você me passasse as infos de private label" |
| ALEMÃO AGROINDÚSTRIA | 09:00–09:01 | "…detalhes da empresa e **PREÇOS**" |
| Blue Sky Consultancy | 12:12–12:41 | Specs completas de exportação/FBA |
| Geraldo | 12:39 | "Boa tarde" |
| Mateus | 14:28 | "Boa tarde" |
| Leonardo José | 14:45–14:46 | "valor das sacas dos cafés especiais em grãos" |
| Prof. Sebastião Alves | 15:30 | Lead de 500kg–1t/mês, aguardando; terminou com "?" |
| Douglas Passos (10/07) | 18:17 | "Olá boa noite" |
| Regina (10/07) | 19:06 | Parceria de mídia (rádios) |
| Mayckel Willyan (10/07) | 19:27 | "Estava falando com Valéria e ela me passou seu contato" |

Os casos noturnos (10/07 após 18h) são defensáveis; **os 8 casos em horário comercial de hoje não**. Perguntas de preço explícitas (Alemão, Leonardo, Elias) estão envelhecendo há horas.

---

## O que está saudável (não mexer)

- Latência, entrega, estabilidade do LLM (99 registros de `token_usage`, sem gaps), sem loops nem leaks.
- Escuta ativa de qualidade: caso **João Marcos** (Café Pódio, Brasília) — 25 min de áudios longos bem acompanhados, `agendar_retorno` para segunda-feira, ancoragem de contexto (queijo canastra), handoff limpo.
- Fixes de hoje visíveis nos dados: pós-R2 os handoffs respondem antes de despedir; pós-R3 sem novas ocorrências do "?" indevido (caso Fabi 10:26 BRT é anterior ao fix e foi justamente o gatilho dele); ❤️ da ponte funcionou no primeiro caso pós-deploy.

## Recomendações (para priorização — nada foi alterado nesta auditoria)

1. **S1:** tornar a guarda "handoff verbalizado sem tool-call" idempotente quando `encaminhar_humano` já executou no turno (assinatura: 2 cartões em <30s).
2. **S2:** ponte pós-handoff com 3 vias: despedida social → ❤️; pergunta substantiva (preço/MOQ/produto) → responder OU notificar o vendedor com a pergunta; resto → carimbo. Hoje pergunta de preço = carimbo.
3. **Categoria 3:** alerta de SLA para fila do João (ex.: inbound pós-handoff sem resposta humana > 30 min em horário comercial → WhatsApp/Sentry para o time), nos moldes dos alertas wartime já existentes.
4. **C3:** rota de conversa para "sou representante" (descarte suave ou registro específico) para não poluir a fila com handoffs não-compradores.
