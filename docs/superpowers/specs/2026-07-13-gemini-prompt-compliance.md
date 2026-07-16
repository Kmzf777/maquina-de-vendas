# Spec — Compliance Gemini dos prompts do Playbook Hunter (13/07/2026)

Guia de referência: `gemini-prompting-strategies.md` (seção **Gemini 3 → Core prompting principles**,
**Zero-shot vs few-shot**, **Consistent formatting**, **Structured prompting examples**).

Escopo: **forma, não regra de negócio.** A Valéria continua Hunter; nenhuma lei do playbook muda de sentido.

## Auditoria — 4 desvios encontrados

| # | Desvio | Diretriz violada | Arquivo |
|---|---|---|---|
| D1 | `POSTURA_HUNTER` entra na cadeia como Markdown solto, sem delimitador. O `BASE_STATIC` que vem antes é todo XML (`<role>`, `<constraints>`, `<instructions>`) — o modelo não tem fronteira explícita entre "regras base" e "lei de outbound", e a lei que precisa **vencer a regra 26** fica sem marcador de escopo. | *"Use consistent structure: employ clear delimiters… XML-style tags… Choose one format and use it consistently"* + *"Prioritize critical instructions"* | `playbook.py` |
| D2 | Linguagem persuasiva/retórica em vez de imperativa: "se você devolver a condução pro lead, **a conversa morre**", "esse é exatamente o erro que **esta lei existe pra matar**", "Diferença que decide a venda… **Sempre a segunda**". Gasta token e esforço cognitivo sem carregar instrução. | *"Be precise and direct: state your goal clearly and concisely. **Avoid unnecessary or overly persuasive language**"* | `playbook.py` |
| D3 | O playbook é **zero-shot**: só tem exemplos de *intenção* soltos em bullets, nenhum exemplo completo de turno certo × errado. O guia recomenda few-shot sempre, e a falha real de 13/07 é um caso de formato de turno. | *"We recommend to always include few-shot examples. Prompts without few-shot examples are likely to be less effective"* | `playbook.py` / `secretaria.py` |
| D4 | Termos ambíguos não definidos: "com a conversa **ainda viva**", "**fecho genérico** de turno", "pergunta **investigativa**". O modelo tem de inferir o parâmetro. | *"Define parameters: explicitly explain any ambiguous terms or parameters"* | `playbook.py` |

**Conforme (mantém):** o bloco já está posicionado no **início** do prompt de estágio (prioridade de instrução crítica);
é 100% estático (não quebra o implicit caching); a lei anti-carimbo (Lei 4) neutraliza o risco de overfitting dos exemplos.

## Reformatação

1. **D1 — envelopar em XML.** `POSTURA_HUNTER` passa a ser `<outbound_playbook priority="max">…</outbound_playbook>`,
   com as 4 leis como sub-blocos nomeados. Formato coerente com o repositório, que já usa contêiner XML +
   Markdown interno (`<constraints>` no base, `<few_shot_examples>` nos estágios).
2. **D2 — imperativo seco.** Toda linha retórica vira instrução ou é cortada. Regra de escrita adotada:
   cada linha é **uma ordem** (OBRIGATÓRIO / PROIBIDO / faça X), nunca um argumento de convencimento.
3. **D3 — few-shot com formato consistente.** Um par `PROIBIDO (falha real 13/07)` × `CORRETO` é adicionado ao
   bloco `<few_shot_examples>` **já existente** na secretaria outbound, no mesmo formato dos exemplos vizinhos
   (`User:` / `Assistant:` / `Nota:`) — o guia é explícito em manter o formato dos few-shots idêntico entre si.
   Nada de criar um formato novo dentro do playbook.
4. **D4 — desambiguação.** Definições explícitas no próprio bloco:
   - **conversa viva** = o lead não foi descartado, não houve handoff e a IA segue ativa;
   - **pergunta investigativa** = pergunta em que VOCÊ escolhe o assunto e o lead só precisa responder;
   - **fecho de turno** = a última bolha da sua resposta.

## Invariantes (não podem mudar)

- As 4 leis (Ponte de Contexto, Postura Ativa + blacklist, Cliente conhecido = recompra / override da regra 26,
  Anti-carimbo) mantêm o mesmo conteúdo normativo.
- Os 20 casos de `tests/test_outbound_postura_hunter_2026_07_13.py` continuam verdes sem afrouxar asserção.
- Nenhum arquivo de `valeria_inbound/` nem `base.py` é tocado.
- O bloco continua estático e no início do prompt de estágio (cache + prioridade).
