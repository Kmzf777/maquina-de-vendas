# Auditoria das conversas da Valéria — 2026-06-22

Auditoria holística do comportamento da Valéria (inbound + outbound) em produção
no dia 2026-06-22. Fonte: tabela `messages` (Supabase prod), todas as conversas do dia.

## Método

- Persona registrada em `messages.agent_persona`. Hoje: **29 conversas `valeria_inbound`**
  (271 msgs da IA) e **0 `valeria_outbound`**.
- O "outbound" real são mensagens `sent_by='broadcast'` (47) e `sent_by='followup'` (8),
  enviadas pelo broadcast worker — que **não** marca `agent_persona`. Quando o lead
  responde, a resposta roda como `valeria_inbound`.

## Números do dia

| Métrica | Valor |
|---|---|
| Disparos broadcast | 47 |
| Responderam ao disparo | 24 (51%) |
| Opt-outs ("Parar Mensagens") | 3 |
| Soft-rejections (sem interesse) | 2 |
| Handoffs qualificados p/ João | 7 |
| Conversas mortas no stall "segundinho" | 5 |
| Áudios com falha de transcrição | 9 |

## Achados

### 1. [ALTA] `valeria_outbound` é persona morta em produção
A abertura outbound ("atualizando registros / Falo com {nome}?") é um template do broadcast
worker; a partir da 1ª resposta tudo roda como `valeria_inbound`. O prompt `valeria_outbound`
(registry + `context.py`) **nunca é aplicado** às conversas reais. Ou se conecta o
`agent_profile_id` outbound às conversas de broadcast, ou se remove a persona para não
manter dois caminhos divergentes.

### 2. [ALTA] Dead-end do fallback "me dá um segundinho que já te respondo"
`orchestrator.py:42` `_SAFETY_FALLBACK_MESSAGE` é a rede de segurança para resposta vazia do
LLM (gemini-2.5-flash gastando o budget em "thinking" e devolvendo texto vazio). Dispara em
mensagens vazias/cortadas (sticker, reação, mídia sem texto). **Problema:** promete uma
resposta futura que nunca vem — não existe processamento diferido. Hoje matou **5 conversas**
(Marcos, Valdemar, Grazieli, etc. — "segundinho" foi a última mensagem da IA).
- **Correção:** trocar por algo sem falsa promessa, ex.:
  "desculpa, acho que sua mensagem chegou cortada aqui" + "consegue me mandar de novo, em texto?"

### 3. [ALTA] Transcrição de áudio falhando (9 ocorrências)
Vários `[audio: nao foi possivel transcrever]` (ex.: Cris Bonanno, 4x). Quando funcionou, veio
truncada ("Oi Valéria bom dia querida ___ __ mandar um áudio"). O lead Cris tentou áudio 4x,
recebeu o fallback repetidamente e quase abandonou. Investigar o caminho de transcrição em
`processor.py::_resolve_media` (modelo `gemini-3-flash-preview` para `audio.transcriptions`).

### 4. [MÉDIA] Loop de pergunta repetida — ignora desengajamento (Valdemar)
Valdemar (conv `ac01493b`): a Valéria perguntou **"com quem eu to falando?" 3x seguidas**,
mesmo o lead respondendo "Pode entrar em contato nesse número" e "Obrigado" (desengajando), e
mesmo já tendo o nome "Valdemar Martins" no cadastro. Viola regra 2 ("não repetir perguntas")
e a leitura de desengajamento. A regra anti-redundância entre turnos (deploy de hoje) ajuda,
mas o loop de "qual seu nome?" precisa de guardrail próprio.

### 5. [MÉDIA] Duplicação de rapport por fragmentação (valida o fix de hoje)
Cris Bonanno, 14:27:18 e 14:27:21 — dois turnos quase idênticos ("que projeto bacana o seu, o
'Café com Fé'" / "muito legal essa ideia de conectar histórias..."), porque dois áudios
chegaram a ~15s um do outro. É exatamente o caso atacado pelo fix de hoje (janela 8→15s +
regra 24 anti-redundância). Confirma a correção; monitorar se reincide.

### 6. [MÉDIA] Segmentação: cliente existente recebe funil de lead novo (Grazieli)
Grazieli já é **cliente** ("a gente já trabalha com o Café Canastra"), mas recebeu o disparo
genérico de "atualizando cadastro" e a Valéria rodou o funil de lead novo (qualificar, enviar
fotos, pitch "já pensou em oferecer café que conta a origem?") até a lead revelar que já compra.
A Valéria recuperou bem ("que bacana que você já é nossa parceira"), mas a lista de broadcast
inclui clientes ativos — problema de segmentação a montante.

### 7. [MÉDIA] Abertura outbound provoca "qual o motivo do contato?"
O pretexto "atualizando registros / Falo com você?" gera suspeita. Everton respondeu
"Brasileiro, **mas qual o motivo do contato?**" e a Valéria deu uma justificativa possivelmente
inventada ("a gente viu que você demonstrou interesse nos nossos cafés") — risco de violar
ANTI-PREMISSA. Alan respondeu "Sim, mas não tenho interesse em comprar". O opener vende como
"confirmação de cadastro" e a IA emenda direto numa pergunta de qualificação
("mercado brasileiro ou exportação?") sem ponte — salto que explica parte do drop-off.

### 8. [BAIXA] 2ª bolha pós-"Sim" é idêntica e robótica entre leads
Todo lead que responde "Sim" recebe ack variado ("que bom"/"ah, massa"/"que bom te encontrar")
+ a **mesma frase literal**: "pra te direcionar da melhor forma, sua demanda é pro mercado
brasileiro ou pra exportação/mercado externo?". "Exportação" como 1º qualificador é de baixo
valor (quase todos são mercado interno). Considerar abrir com algo mais natural/segmentado.

### 9. [BAIXA] Mensagens canônicas fora do padrão de humanização
Os textos de opt-out/soft-rejection das tools quebram as convenções novas (regra 22 "sem
ponto final", minúsculas): "Entendido, sem problema. Não entrarei mais em contato",
"Sem problema, Alan, fico à disposição". Vêm das tools (não do LLM), então passam ao largo das
regras do prompt. Idem o fallback de mídia "Oi! Acabei não conseguindo abrir o que você
mandou..." (tem "!" e maiúscula). Padronizar os canned texts com a persona.

### 10. [BAIXA] Personalização do disparo com handle como nome
"Falo com cassianofonseca15 neste número?" / "Falo com Brunor_barista neste número?" — usa o
push_name/handle do WhatsApp como nome próprio. Soa robótico. Tratar nomes não-confiáveis
(com dígitos/underscore) com fallback sem nome.

## Pontos fortes (manter)

- **Betty** (conv `5ee5cf02`): fluxo modelo — saudação → nome → qualificação → stage → rapport
  curto → fotos → produto → preço de referência → handoff correto na pergunta de volume (>1kg).
- **Grazieli**: rapport contextual genuíno ("o chimarrão é forte aí no Sul", "loja de produtos
  naturais tem público ótimo pra café especial").
- **Ricardo**: humanização (minúsculas, sem ponto final, sem acento robótico) consistente.
- Detecção de frustração/opt-out funcionando (3 opt-outs e 2 soft-rejections tratados certo).

## Recomendações priorizadas

1. **Fallback "segundinho"** (orchestrator.py:42) → mensagem sem falsa promessa. *Quick win.*
2. **Transcrição de áudio** — investigar falha (9 hoje); é perda direta de leads.
3. **Guardrail anti-loop de "qual seu nome?"** — no máx. 1 repetição; se o lead desengaja, parar.
4. **Decisão sobre `valeria_outbound`** — conectar de verdade ou remover.
5. **Segmentação de broadcast** — excluir clientes ativos e tratar handle-como-nome.
6. **Padronizar canned texts** (opt-out/soft/mídia) com as convenções de humanização.
7. **Repensar o 1º qualificador outbound** (exportação raramente se aplica).
