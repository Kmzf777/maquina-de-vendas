# Prioridades de correção — Valéria (baseline 2026-04-22T11-47-10)

Fonte: 4 transcripts (R1, R2, R3, R5). R4 não concluiu por ReadTimeout de backend.

## Resumo por persona

| Persona | Score | Handoff | Turnos | Forbids | Falha principal |
|---|---|---|---|---|---|
| R1 Representante | **9** | ✅ | 16 | ❌ PRECO_FRETE | Ignorou pergunta dupla sobre pedido mínimo; prometeu preços finais |
| R2 Marca cautelosa | **3** | ❌ max_turns | 20 | ❌ DESCONTO | Loop de respostas genéricas frente a objeção de preço; improvisou desconto de R$44,90 |
| R3 Grãos próprios | **4** | ❌ max_turns | 20 | ok | **Inventou torrefações, endereços e telefones no RJ**; perdeu contexto e reiniciou qualificação |
| R5 Lojista amostra | **7** | ❌ max_turns | 20 | ok | Ofereceu microlote como solução, mas microlote tinha o mesmo mínimo e café diferente — criou confusão |

Padrão sistêmico: **3 de 4 personas NÃO fizeram handoff**. Única que passou (R1) passou por mérito do lead, não da condução.

## Prioridades de correção

### P0 — bloqueiam venda / risco reputacional

**1. Proibir invenção de terceiros (R3)**
Bot inventou nomes/endereços/telefones de 2 torrefações no Rio. Risco legal e de confiança.
Regra sugerida no system prompt:
> NUNCA mencione nomes, telefones, endereços ou contatos de terceiros (torrefações parceiras, distribuidores, clientes, concorrentes). Se o lead pedir indicação, responda que essa informação é passada pelo João Bras na continuidade do atendimento e chame `encaminhar_humano`.

**2. Preços sempre como referência, nunca compromisso final (R1 + R2)**
Bot disse "R$27,70", "R$46,70", "R$44,90 já com embalagem". A política é só o comercial fechar. Regex forbid já pega — falta reforçar no prompt.
Regra sugerida:
> Ao falar de preço use SEMPRE verbo de referência ("gira em torno de", "faixa de"), nunca compromisso ("sai a", "fica", "é"). Nunca some, arredonde ou invente combo de desconto. Se o lead insistir em fechamento, chame `encaminhar_humano`.

**3. Circuit breaker anti-loop → handoff forçado (R2, R3, R5)**
3 de 4 corridas bateram max_turns sem handoff. Bot fica repetindo "quer que eu te explique X?".
Regra sugerida:
> Se o lead repetir a mesma objeção duas vezes, OU se você se pegar oferecendo "quer que eu te explique/envie X?" pela 3ª vez no mesmo tópico, chame `encaminhar_humano` em vez de continuar sozinha. Handoff é vitória, não desistência.

### P1 — qualidade de condução

**4. Pergunta dupla deve ter resposta dupla (R1)**
Lead perguntou "pedido mínimo no private label E no atacado?" — bot mandou fotos e perguntou outra coisa.
Regra sugerida:
> Quando o lead fizer 2+ perguntas em uma mensagem, responda TODAS antes de oferecer próximo passo.

**5. Microlote tem regra clara (R5)**
Bot ofereceu microlote para contornar objeção de 100un, mas microlote também tem 100un (ou 50un só se embalagem própria) e é café diferente.
Regra sugerida:
> Microlote só é alternativa de pedido mínimo quando lead usa embalagem própria (50un); nunca apresente como amostra do mesmo café que ele provou. Se contradizer a objeção, NÃO ofereça.

### P2 — estilo / manutenção

**6. Reduzir bordões "quer que eu te…"**
Aparece em R1, R2, R5. Adicionar ao prompt: variar entre "posso te mostrar", "te passo isso", "te envio", ou simplesmente enviar.

**7. Cabeçalhos longos de preço são robóticos (R1)**
Listagem em 10 linhas de preço foi classificada como robotizada. Regra: quando o lead pedir "tabela", sugerir catálogo/handoff em vez de despejar lista.

## O que o runner está capturando bem

- Forbids regex pegaram 2 violações reais e sutis (PRECO_FRETE em R1, DESCONTO em R2) que o juiz Gemini passaria batido.
- `hard_check has_encaminhar_humano` isolou com precisão o problema sistêmico de não-handoff.
- `linhas_robotizadas` do soft_check destacou os bordões repetitivos.

## O que o runner NÃO pega hoje

- **Alucinação de entidades** (R3: nomes/telefones inventados) — não tem regex possível; depende do juiz soft. Considerar forbid adicional tipo `\btorrefa` + `\brua\b` em mensagens Valéria.
- **Loops de pergunta aberta** — juiz detectou, mas não é hard check. Considerar hard_check: "mais de 3 mensagens consecutivas terminando em `?` sem avanço de stage".

## Próximo passo sugerido

Aplicar P0 (1–3) no system prompt da Valéria, rodar novo rehearsal V2 e comparar contra este baseline (SHA `ebf5557`). P1/P2 ficam para iteração seguinte.
