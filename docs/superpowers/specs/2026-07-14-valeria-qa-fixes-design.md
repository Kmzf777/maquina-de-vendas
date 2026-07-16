# Spec — Correções de QA da Valéria (auditoria 14/07)

**Objetivo de produto:** a Valéria (a) **nunca fala sobre "o sistema"/"catálogo"/"erro"** ao
cliente e (b) **nunca descarta um lead que acabou de fazer uma pergunta**. Secundariamente:
não promete mídia que não envia, não presume que um terceiro citado é da equipe, e não
reinicia a qualificação de um lead com histórico.

Escopo: casos **#1–#5** do relatório `docs/superpowers/reports/auditoria_valeria_2026-07-14.md`.
Fora de escopo: #6–#8 (baixa prioridade, backlog).

Princípios do repo respeitados: guardas determinísticas são **funções puras** em
`adherence.py` (sem I/O), fail-open, com teste unitário no mesmo commit; o cliente **nunca vê
a cozinha**; paridade inbound/outbound; catálogo é a fonte única de preços.

---

## #1 — Anti-vazamento de erro de sistema ("cozinha")

**Falha:** a saída interna de `calcular_orcamento` ("Produto '…' não encontrado no catálogo de
atacado") foi repassada literalmente ao cliente, 2×.

**Defesa em profundidade (2 camadas):**

1. **Prevenção (prompt/tool):** reescrever os dois retornos de "não encontrado" em
   `tools.py` (`calcular_orcamento`, ~1548-1556) para um formato explicitamente **interno**
   com instrução de tom, ex.:
   `"[INTERNO — NÃO REPASSAR] A variação '…' não existe no catálogo. Disponíveis: … .
   Confirme com o cliente em tom de vendedora; JAMAIS diga 'sistema', 'catálogo', 'não
   encontrei' ou 'erro'."`

2. **Backstop determinístico (garantia):** nova função pura
   `strip_kitchen_leak(text) -> str` em `adherence.py`, ligada a
   `_sanitize_assistant_text` (orchestrator), que **remove o trecho-vazamento** preservando o
   resto útil da frase. Casa (texto normalizado, sem acento/caixa) e remove os spans do texto
   ORIGINAL — mesma técnica de `strip_prohibited_phrases`. Alvos:
   - `o sistema (não )?(encontrou|achou|acha|localizou) … (no catálogo…)?`
   - `(não )?(encontrei|achei|localizei) … no catálogo …`
   - `deu (um )?erro …`, `o sistema travou`, `o sistema (está|tá) fora`, `erro no sistema`,
     `bug`, `não achei no catálogo`.
   Fail-open: se a remoção esvaziar o texto, devolve o original (a camada 1 é a rede
   primária nesse caso patológico). Loga o vazamento (como os outros sanitizers).

**Testes:** a mensagem real do caso Thiago vira "opa, ele tem as opções de moído ou em grãos,
…" (trecho útil preservado, cozinha removida); frases de venda legítimas com a palavra
"sistema" fora do contexto de erro (ex.: "sistema Nespresso") **não** são afetadas.

---

## #2 — Fotos prometidas e não enviadas

**Falha:** `media_tool_used` marca **intenção** (tool chamada), não **envio**. Quando
`enviar_foto_produto`/`enviar_fotos` retorna "nao encontrada"/"Nenhuma foto" (sem exceção),
a flag fica `True`, a guarda de fotos verbalizadas é pulada e a promessa "to mandando as
fotos" sai sem foto.

**Correção:**
- Nova função pura `media_result_is_no_send(result) -> bool` em `adherence.py`: `True` quando
  o retorno indica que **nada foi enviado** ("nao encontrada"/"nao encontrado"/"nenhuma
  foto"); `False` para sucesso ("enfileirada(s)") e para no-op idempotente ("ja
  enviada/enfileirada" = fotos já existem na conversa).
- No loop de tools do orquestrador (ramo `else`, ~1069-1071): se
  `func_name in _MEDIA_TOOL_NAMES and media_result_is_no_send(tool_result)` →
  `media_exec_failed = True` (semântica já existente: "não foi de fato").
- Guarda de fotos verbalizadas (~1543): trocar `not media_tool_used` por
  `(not media_tool_used or media_exec_failed)` — a promessa dispara `enviar_fotos` quando a
  tentativa anterior não enviou nada.

**Testes:** com resultado "foto do produto 'X' nao encontrada", a guarda de fotos verbalizadas
passa a disparar; com "4 fotos … enfileiradas" ou "ja enviadas", **não** dispara (evita
envio duplo).

---

## #3 — Abandono de lead que fez pergunta

**Falha:** `registrar_sem_interesse_atual` disparou logo após o lead perguntar "Tenho que
investir?".

**Correção:**
- Nova função pura `contains_open_question(text) -> bool` em `adherence.py`: `True` quando há
  um trecho terminado em "?" cujo conteúdo contém um **interrogativo** (qual, quanto, como,
  quando, onde, quem, por que) ou **verbo/termo de negócio** (tem, teria, posso, poderia, dá
  pra, consigo, preciso, precisa, investir, funciona, custa, vale, mínimo, valor, preço,
  possível). Cortesia pura ("tudo bem?", "ok?", "né?") **não** casa.
- Guarda no loop de tools do orquestrador, ANTES de executar a tool: se
  `func_name == "registrar_sem_interesse_atual" and contains_open_question(user_text)` →
  **aborta** o descarte (não executa), devolve ao modelo um `function_response` instruindo
  "responda a pergunta do lead com o catálogo ANTES de qualquer descarte". Mesmo padrão da
  Guarda 18C (`tools.py:1229`). Fail-open: falso-positivo só faz o modelo responder primeiro
  (comportamento desejado).

**Testes:** "Tenho que investir?" e "qual o valor?" abortam o descarte; "não quero, muito
caro" (sem pergunta) e "tudo bem?" **não** abortam.

---

## #4 — Não presumir que terceiro citado é da equipe (prompt)

**Falha:** a Valéria presumiu que "o Arthur" (citado pelo lead) era da Café Canastra e
encerrou.

**Correção (prompt inbound + outbound):** regra explícita — "Se o lead mencionar uma pessoa
(ex.: 'o Arthur', 'meu contato', 'o representante') sem dizer que é da nossa equipe, **NÃO
presuma**. Pergunte se é o nosso representante antes de encerrar; se não for, retome o
atendimento." Aplicar em `secretaria` (entrada) inbound e outbound.

---

## #5 — Não reiniciar qualificação de lead com histórico (prompt)

**Falha:** re-envio do template da landing page reiniciou a qualificação do zero num lead que
já tinha respondido dias antes.

**Correção (prompt inbound):** regra — "Se a frase de prefill da landing page chegar mas você
**já tem histórico** com este lead (já se apresentou, já perguntou marca do zero, já enviou
fotos), **não reinicie**; retome do ponto em que pararam." Aplicar no `private_label` e na
entrada inbound.

---

## Rodada 2 — itens BAIXOS (#6, #7, #8) — "limpar a mesa"

Prompts (#6, #8) seguem estritamente `gemini-prompting-strategies.md` (Gemini 3): estrutura
consistente com o estilo do arquivo, constraint imperativo (o que fazer E não fazer), few-shot
bad→good variado, instruções críticas em destaque.

### #6 — Prova social incoerente (atacado inbound + outbound)
A linha fixa "Benchmark de mercado" pressupõe que o lead já vende café. Regra CONDICIONAL
adicionada logo após ela: SE o lead já vende café → benchmark atual; SE está começando do zero
/ ainda não vende → PROIBIDO "o café que vendia", usar prova social de ENTRADA (diferenciação/
fuga da guerra de preço); na dúvida, versão neutra de entrada. Few-shot com 2 situações
(bad→good). Arquivos: `valeria_inbound/atacado.py`, `valeria_outbound/atacado.py`.

### #7 — Vazamento de marcador de mídia do histórico (backend + teste)
`render_history_content` envelopa a legenda de foto como `[Foto enviada por você: "…"]` — formato
CORRETO e deliberado para o LLM (fix 13/07, evita o modelo inventar autoria). O bug real: o
modelo ECOOU o marcador como fala e ele chegou ao cliente (onde "você" lê como se o cliente
tivesse enviado). **Decisão técnica:** NÃO alterar o formato do histórico (regrediria o fix
13/07 e o teste `test_history_media_captions_2026_07_13`). Fix definitivo = backstop
determinístico `adherence.strip_media_history_markers` no `_sanitize_assistant_text`, que remove
o marcador-envelope da SAÍDA (nunca chega ao WhatsApp), preservando o resto útil da bolha.
Teste `test_media_marker_leak_2026_07_14.py` (7 casos, inclui a bolha real da CONV 04).

### #8 — Presunção de gênero (base.py)
Nova subseção `## Linguagem neutra de genero` em destaque no bloco `<constraints>`: proíbe
adjetivos/particípios flexionados aplicados ao lead enquanto o gênero não for óbvio pelo nome
próprio (em DOBRO para PJ/empresa); dá alternativas neutras e calorosas ("você tem toda razão",
"faz total sentido"); ressalva que a auto-referência da Valéria segue no feminino; few-shot
bad→good. Mantém o tom caloroso.

## Riscos e mitigação
- Mudanças de código são todas **funções puras + wiring mínimo**, fail-open, cobertas por
  testes. Nenhuma altera contrato de tool nem schema.
- #4/#5 são regras de prompt (comportamentais); efeito parcial esperado — registrados como
  reforço, não garantia determinística.
- Validação: suíte `pytest` completa verde antes do deploy. Deploy = push para `master`
  (dispara Action de produção), conforme autorização explícita do usuário.
