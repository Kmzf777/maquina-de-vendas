# Motor de follow-up do João — nos moldes do da ValerIA

**Data:** 2026-09-18 · **Branch:** `feat/motor-followup-joao` (de `origin/master`)

---

## 1. A decisão

O caminho do builder (semanas de 15 a 17/09) entregou correção real — registro de nós,
validação na ativação, aposentadoria da aba Esteiras, tudo em produção em `1dd0f113` —
mas não entregou **o follow-up do João funcionando**. E a esteira de Reposição, montada
como campanha, provou-se incompatível com a própria ata: `_guard_broken` cancela a
matrícula quando o card muda de coluna, e a ata manda mover o card no primeiro toque.

Rollback do rumo, não do que está em produção:

- **Mantém** `1dd0f113` (verde, testado, e a aposentadoria da aba é coerente com este
  spec — a configuração vai para o modal de follow-up).
- **Descarta** os 5 commits não pushados da remodelagem visual e a Task C1 não commitada.
- **Apaga** as 6 esteiras-campanha do João **e o seed que as recria** a cada start.

## 2. O achado que dimensiona o trabalho

`follow_up_jobs` **já é um executor multi-tipo**, com cinco `job_type` em produção:
`standard`, `ai_scheduled_return`, `ai_reengage`, `handoff_rescue`, `lp_welcome`.

`process_due_followups` despacha por tipo para handlers autocontidos, e
`_stop_reason_applies(reason, job_type)` **já varia as guardas de parada por tipo**.

> **Não escrevemos um segundo motor.** As cadências do João viram novos `job_type` no
> mesmo `follow_up_jobs`, no mesmo scheduler. O trabalho real é **um handler novo** e um
> **agendador** que cria os jobs.

Herda-se pronto e testado: agendamento, janela comercial, jitter, recuperação de job
travado, blacklist, número errado, conversa finalizada, cancelamento na resposta.

## 3. A diferença que justifica o handler novo

A ValerIA gera o texto por LLM porque a janela de 24h está aberta. O lead do João está em
silêncio por definição — janela fechada — então **só template aprovado sai**.

O handler do João portanto:
- monta os componentes do template (reusa `broadcast/worker.py::_build_template_components`);
- resolve o canal do vendedor;
- **não** chama LLM.

## 4. As cadências, e a ata

| Cadência | Gatilho | Toques | Ata |
|---|---|---|---|
| **Novo** | card 2 dias em "Novo" | 1 toque | 01:07:10 ("36 horas… é de dois dias") |
| **Em conversa** | card 2 dias em "Em conversa" | 7 toques em ~30 dias | 41:02 ("deve durar uns 30 dias") |
| **Reposição** | **45 dias** em "Cliente Ativo" | toque, depois de 15 em 15 | 26:35, 34:24 |
| **Em atenção** | 90 dias sem comprar | **1 mensagem a cada 3 dias** até dizer que não quer | 38:08, 41:12 |

Duas regras de resposta da ata:

- botão **"ainda tenho estoque"** → adia **60 dias**, não recomeça a contagem (41:40);
- botão de saída → opt-out real.

E o requisito que o caminho do builder nunca entregou, **na ata desde o início**:

> **33:28 — "45 dias, mas opção do João editar o número de dias."**

## 5. A configuração sai do código

`follow_up/cadence.py` é config-as-code. Para o João a definição vai para uma tabela,
**semeada a partir do código** — o código continua sendo a origem, o banco vira a
sobreposição editável.

Editável por cadência: **dias de cada toque**, **template de cada toque**, **o prazo do
gatilho** e **liga/desliga**.

**Não** editável: adicionar ou remover toques. Mudar a forma da cadência continua sendo
mudança de código — é o que impede a tela de virar builder de novo, que é o erro que este
spec corrige.

## 6. A tela

`/campanhas > Follow-up` já tem o `DefinitionStrip`, que lê `/api/cadence/definition` e
mostra a cadência da ValerIA **somente leitura**. Ele vira o editor dos dois motores:

- seletor ValerIA / João;
- por toque: dias e (no João) template, escolhido entre os **aprovados** na Meta;
- prazo do gatilho e liga/desliga por cadência;
- **ligar exige template aprovado em todo toque** — mesma trava que já existia na aba
  Esteiras, e que impede a campanha que inscreve, não envia e caminha até o fim.

Para a ValerIA, editável são os dias; o objetivo de cada toque continua no código, porque
é prompt de LLM.

## 7. Fora de escopo

- **O espelho no builder.** Cortado da v1 de propósito: não é urgente, e sem ele o builder
  apenas não mostra as cadências do João. Vem depois, no padrão de `system_cadence.py`.
- Reverter `1dd0f113`.
- Ligar qualquer cadência: tudo nasce **desligado**.
- Aplicar SQL ou migration.

## 8. O risco, nomeado

O scheduler tem **1.877 linhas** e 14 referências específicas à ValerIA, e o caminho dela
é **o único follow-up que funciona hoje em produção** (8.140 jobs na história). O ramo
novo não pode tocar o caminho dela.

Mitigação: o handler do João é **função nova**, e o único ponto compartilhado é o
despacho por `job_type` em `process_due_followups`. Nenhuma linha do caminho `standard`
muda. Teste de regressão dedicado ao caminho da ValerIA antes e depois.

## 9. Como se prova

- Um job do João percorre a cadência inteira nos prazos da ata, com a janela comercial e
  os dias úteis respeitados.
- `_stop_reason_applies` barra o job do João nas mesmas condições que barra a ValerIA
  (blacklist, número errado, conversa finalizada).
- O caminho `standard` da ValerIA é **byte-a-byte** o mesmo: teste que roda a cadência
  dela antes e depois do ramo novo e compara o resultado.
- "Ainda tenho estoque" adia 60 dias sem recomeçar; botão de saída grava opt-out real.
- Ligar cadência com template pendente é **recusado**, nomeando o template e o status.
- A configuração do banco sobrepõe o código; sem linha no banco, vale o código.
