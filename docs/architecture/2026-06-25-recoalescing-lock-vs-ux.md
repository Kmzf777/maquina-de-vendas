# Re-Coalescing por lead: empilhamento exige guard in-flight, não só abort pós-lock

**Data:** 2026-06-25 · **Origem:** auditoria forense do lead `5533999429785`
**Código:** `backend/app/buffer/processor.py` (`_has_newer_inbound`, abort pós-lock, guard in-flight)

## Contexto

O lead mandou uma **imagem** (`14:51:45`) e, ~16 s depois, um **texto** (`14:52:07`). A
Valéria respondeu **dois blocos empilhados e contraditórios** (um pedindo "qual café te
chamou", outro já em `private_label` perguntando "você tem marca registrada?"), parecendo
que falou sozinha duas vezes sem esperar o cliente.

A autópsia provou que **o mutex por lead (`lead_run_lock`) funcionou**: os dois turnos
foram serializados (o 2º esperou ~25 s o 1º liberar). Não houve race, não houve loop de
tool, não houve limite de funil.

## Distinção central: Race Condition ≠ UX

> **Lock resolve concorrência. Lock NÃO resolve aglutinação.**

- **Race condition** (resolvida pelo `lead_run_lock` em 2026-06-24, lead `5544991611703`):
  dois workers do mesmo lead rodando ao mesmo tempo, lendo histórico stale → saída
  duplicada. O lock serializa e elimina isso.
- **Problema de UX** (este caso): dois inbounds **legítimos e distintos** viram dois turnos
  serializados, mas **sem aglutinação** as respostas empilham. O lock, por design, só
  *enfileira* — não *funde* contextos.

Tratar o empilhamento como "falha de lock" leva a caçar infra que está sã. **Cheque os
turnos antes de culpar a trava.**

## Padrão adotado: duas defesas, uma régua

Régua única = `_has_newer_inbound(conversation_id, watermark)`, onde `watermark` é o
`created_at` (autoritativo do DB) do inbound que engatilhou o worker.

1. **Stale worker abort (pós-lock):** ao adquirir o lock, se já há inbound mais novo,
   aborta o turno em silêncio. Cobre a **pilha de mensagens enfileiradas** atrás do lock —
   só o worker mais novo roda e responde o contexto completo.

2. **Guard in-flight (cauda do lock):** entre as bolhas do envio, se aparece inbound mais
   novo, corta as bolhas restantes + a mídia diferida e libera o lock cedo.

**Por que as duas:** o abort pós-lock **não pega** o caso onde o inbound novo chega *depois*
que o worker-holder já passou pelo check (foi exatamente o incidente: a imagem já estava
enviando quando o texto chegou). É o **guard in-flight** que fecha esse caso — o turno da
imagem detecta o texto no meio do envio e para.

## Decisão correlata: mídia diferida fica DENTRO do lock

Mover o envio das fotos para fora do lock parecia "otimizar a cauda", mas o lock é o
**único serializador por lead**: fora dele, as fotos do turno antigo **interleavam** com o
texto do turno novo. Mantemos a mídia sob o lock e usamos o **guard in-flight** para o
mesmo ganho (liberar cedo) **sem quebrar a ordem**.

## Princípio: fail-open

`_has_newer_inbound` retorna `False` em erro de leitura ou sem watermark. **Nunca abortar às
cegas** — engolir a única resposta de um lead legítimo é pior que o raro empilhamento que
esta trava existe para evitar. Mesma filosofia de `_ai_still_enabled` e dos dedup layers.

## Resíduo conhecido

Se o inbound novo chega *depois* da última bolha (nada mais a enviar e o lock já liberou),
ainda viram dois turnos. Fechar isso pediria um debounce pós-resposta (mudança de UX maior)
— fora do escopo desta entrega.
