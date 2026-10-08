/**
 * O contrato do modal "ValerIA de Botões" com `GET /api/valeria-flow`.
 *
 * Três componentes leem esta resposta (a casca `valeria-flow-modal.tsx`, o editor
 * `valeria-flow-editor.tsx` e a aba de canais `valeria-flow-channels.tsx`). Os tipos
 * moram aqui e não em cada um deles pela mesma razão que a FUSÃO de overrides mora no
 * servidor (cabeçalho de `backend/app/button_flow/valeria_flow_router.py`): três
 * declarações da mesma forma divergem, e a que divergir cala — `undefined` não
 * quebra build, só apaga o texto na tela.
 *
 * ── Estes tipos foram escritos LENDO o router, não a especificação ──────────────
 * Onde a spec do modal e `valeria_flow_router.py` discordam, aqui vale o router (é
 * ele que serializa). Os três pontos em que discordavam estão marcados com
 * `DIVERGÊNCIA` abaixo, porque são exatamente os campos que um painel leria pelo
 * nome errado e mostraria vazio.
 */

/** O ramo comercial do nó. `entrada` é só o N0, que pergunta o setor. */
export type RamoFluxo = "entrada" | "atacado" | "private_label" | "consumo" | "exportacao";

/**
 * Como a mensagem sai no WhatsApp. `foto_botoes` manda a foto no header. `carrossel`
 * só existe na v2: as vitrines (VA/VP) saem como cards com foto, um por produto.
 */
export type TelaFluxo = "lista" | "botoes" | "foto_botoes" | "carrossel";

/**
 * As duas versões da ValerIA de Botões que o MESMO router serve (contrato C7 do plano
 * `2026-10-08-valeria-botoes-v2-vitrine.md`): toda rota de `/api/valeria-flow` aceita
 * `?flow_id=`, e sem ele o backend responde pela v1. A v2 vive AO LADO da v1 — a
 * conversa em andamento termina na versão em que começou —, então o editor escolhe
 * qual das duas está editando e a ativação diz para qual delas aponta o canal.
 */
export type FlowIdValeria = "valeria_botoes_v1" | "valeria_botoes_v2";

/**
 * Um rótulo que saiu do ar. O motor (`valeria_engine._casar`) usa o par
 * `botao_id`/`rotulo` para ainda aceitar o clique de quem recebeu a tela antiga —
 * por isso o histórico é PAR, e não só o texto.
 */
export interface RotuloAntigo {
  botao_id: string;
  rotulo: string;
  em: string;
}

/**
 * Um botão. `id` é o contrato estável com o motor; `rotulo` é o único campo
 * editável. `destino` e `grava` viajam só para a tela explicar o efeito do clique —
 * `ConteudoUpdate` no backend não tem campo onde recebê-los de volta.
 */
export interface BotaoFluxo {
  id: string;
  rotulo: string;
  rotulo_default: string;
  /** Só-leitura: o nó ou terminal a que este botão leva ("N2", "T_HANDOFF"). */
  destino: string;
  /** Só-leitura: pares `[campo, valor]` que o clique grava no lead. */
  grava: [string, unknown][];
  descricao: string;
  /** O limite da Meta DESTE botão: 24 em tela de lista, 20 em botão comum. */
  limite_rotulo: number;
  editado: boolean;
}

/**
 * Um card do carrossel da v2. Só o `corpo` é editável, e ele grava pela chave
 * `card:<id>` (contrato C7). O corpo traz marcadores `{preco:<nome do produto>}` que o
 * backend troca pelo preço do catálogo NO ENVIO; o limite da Meta (160 caracteres, no
 * máximo 2 quebras de linha) vale DEPOIS dessa troca — por isso o `PUT` pode voltar 422
 * com um texto que, cru, parecia caber.
 */
export interface CardFluxo {
  id: string;
  corpo: string;
  corpo_default: string;
  /**
   * A chave do `PUT`/`DELETE`, CANÔNICA: `card:<nó>:<id>`. O id do card não é único no
   * fluxo (`microlote` está na vitrine do atacado e na da marca própria), e o atalho
   * `card:<id>` de um id repetido é 400 no backend. Os campos abaixo são do serializador
   * (`_card_json`); a tela tem reserva para cada um, porque o contrato mínimo é
   * `{id, corpo, corpo_default}`.
   */
  chave?: string;
  tipo?: "card";
  no?: string;
  editado?: boolean;
  /** 160: medido DEPOIS de trocar os preços. */
  limite?: number;
  /** 2. */
  limite_quebras?: number;
  foto?: string;
  rotulo_botao?: string;
}

/**
 * Um texto da v2 que não é tela nem desfecho: as regras do atacado, o "como funciona"
 * da marca própria e cada resposta de FAQ (`faq:<ramo>:<faq_id>`). Grava pela `chave`,
 * pela MESMA fresta do `PUT` de qualquer nó.
 */
export interface TextoFluxo {
  chave: string;
  corpo: string;
  corpo_default: string;
  /** Do serializador (`_reservado_json`); a tela tem reserva para os dois. */
  rotulo_interno?: string;
  editado?: boolean;
}

/** Um nó conversacional: corpo + botões, ambos editáveis. */
export interface NoFluxo {
  id: string;
  tipo: "no";
  rotulo_interno: string;
  tela: TelaFluxo;
  ramo: RamoFluxo;
  corpo: string;
  corpo_default: string;
  foto: string | null;
  produto: string | null;
  botoes: BotaoFluxo[];
  editaveis: string[];
  rotulos_antigos: RotuloAntigo[];
  editado: boolean;
  /** Só na v2, só nas vitrines (`tela: "carrossel"`). Ausente na v1. */
  cards?: CardFluxo[];
}

/**
 * Um desfecho. Só o `corpo` é editável — os campos de EFEITO existem para a tela
 * dizer ao operador o que aquele desfecho FAZ, e não têm caminho de volta.
 *
 * DIVERGÊNCIA (1/3): um terminal NÃO tem `tela`, `ramo`, `foto`, `produto`,
 * `botoes` nem `rotulos_antigos` — `_terminal_json` não os serializa. Um `ItemFluxo`
 * único com esses campos faria o editor ler `item.botoes.map(...)` num terminal e
 * estourar em runtime. Daí a união discriminada por `tipo`.
 *
 * Atenção ao nome repetido: aqui `prazos` é um BOOLEANO ("este terminal oferece a
 * folha 30/60/90"), enquanto `FluxoResposta.prazos` é a LISTA daqueles prazos.
 */
export interface TerminalFluxo {
  id: string;
  tipo: "terminal";
  rotulo_interno: string;
  corpo: string;
  corpo_default: string;
  vendedor: string | null;
  tags: string[];
  silenciar_ia: boolean;
  handoff: boolean;
  optout: boolean;
  prazos: boolean;
  editaveis: string[];
  editado: boolean;
}

/**
 * O nudge e o rótulo do botão que abre a folha de opções: texto que o lead LÊ e que
 * não pertence a nó nenhum. `valeria_flow_content` é chaveada por `node_id`, então os
 * dois têm chave reservada e entram pela MESMA fresta de qualquer nó.
 *
 * DIVERGÊNCIA (2/3): a spec descreve `rotulo_lista` como
 * `{chave, rotulo, rotulo_default, editado}`. `_reservado_json` NÃO tem `rotulo` nem
 * `rotulo_default` — os dois reservados guardam o texto em `corpo`/`corpo_default`,
 * porque é `corpo` que o `PUT` aceita e é `corpo` que a coluna tem. Ler
 * `rotulo_lista.rotulo` devolveria `undefined` e o campo abriria vazio; salvar esse
 * vazio cairia em "o rótulo do botão de lista não pode ficar vazio" (400).
 */
export interface ReservadoFluxo {
  chave: string;
  id: string;
  tipo: "reservado";
  rotulo_interno: string;
  corpo: string;
  corpo_default: string;
  editaveis: string[];
  editado: boolean;
  /** Só em `rotulo_lista`: o limite de 20 caracteres da Meta. */
  limite?: number;
  /** Só em `nudge`: quantos reoferecimentos o motor manda no máximo. */
  teto?: number;
}

/** Qualquer coisa que o `PUT` devolve — os três serializadores do router. */
export type ItemFluxo = NoFluxo | TerminalFluxo | ReservadoFluxo;

/** Os tetos da Meta. A tela conta caracteres a partir DESTES números. */
export interface LimitesFluxo {
  rotulo_botao: number;
  titulo_lista: number;
  desc_lista: number;
  max_botoes: number;
  max_linhas_lista: number;
}

/**
 * Uma linha da folha 30/60/90 do `T_ADIAR`. Só-leitura mesmo no banco: mora em
 * `flows.PRAZOS`, que a Recuperação também serve.
 *
 * DIVERGÊNCIA (3/3): a spec descreve `{id, titulo, dias}`. O router serializa
 * `{id, rotulo, destino, dias, editavel}` — não existe `titulo`. E `dias` vem de
 * `DIAS_POR_PRAZO.get(botao.id)`, um `.get()` sem default: é `number | null`.
 */
export interface PrazoFluxo {
  id: string;
  rotulo: string;
  destino: string;
  dias: number | null;
  editavel: boolean;
}

/** A resposta inteira de `GET /api/valeria-flow`, com os overrides já mesclados. */
export interface FluxoResposta {
  flow_id: string;
  no_entrada: string;
  limites: LimitesFluxo;
  editaveis: { no: string[]; terminal: string[] };
  nos: NoFluxo[];
  terminais: TerminalFluxo[];
  nudge: ReservadoFluxo;
  rotulo_lista: ReservadoFluxo;
  prazos: PrazoFluxo[];
  /**
   * Só na v2: as chaves de `CHAVES_TEXTO` do registry. Inclui as duas reservadas de
   * sempre (nudge e botão de lista), que o editor já mostra em "Textos soltos" — ele as
   * filtra para não desenhar o mesmo texto duas vezes.
   */
  textos?: TextoFluxo[];
}

/**
 * O corpo do `PUT /api/valeria-flow/{node_id}`. `rotulos` é um MERGE parcial no
 * backend (só o botão que mudou já basta), e só nó o persiste: mandar `rotulos` num
 * terminal ou num reservado é 400, não 200 silencioso.
 */
export interface ConteudoUpdate {
  corpo?: string;
  rotulos?: Record<string, string>;
}

/**
 * A função de salvar, servida pela casca aos dois painéis.
 *
 * Resolve com o item já atualizado (o `PUT` devolve `_item_json`) ou com `null` se o
 * backend recusou — nesse caso a mensagem dele já está em `PainelProps.erro`, escrita
 * para o operador. Não rejeita: um painel que esquecesse o `catch` derrubaria o modal.
 */
export type SalvarConteudo = (nodeId: string, patch: ConteudoUpdate) => Promise<ItemGravado | null>;

/**
 * O que um `PUT`/`DELETE` bem-sucedido devolve. Para nó, terminal e reservado é o
 * `_item_json` mesclado; para `card:<id>` e para os textos da v2 a forma é a do
 * serializador do backend, e o painel só precisa saber que DEU CERTO (não-nulo).
 */
export type ItemGravado = ItemFluxo | CardFluxo | TextoFluxo;

/**
 * `DELETE /api/valeria-flow/{node_id}`: volta ao default do registry. Mesma
 * assinatura e mesmo contorno de erro do `salvar` — é por isso que `corpo_default`
 * viaja no `GET`.
 */
export type RestaurarConteudo = (nodeId: string) => Promise<ItemGravado | null>;

/** Props do painel da aba "Fluxo" (`valeria-flow-editor.tsx`). */
export interface PainelFluxoProps {
  dados: FluxoResposta;
  salvar: SalvarConteudo;
  restaurar: RestaurarConteudo;
  /** O `node_id` em gravação agora, ou `null`. Um por vez: a tela salva um nó só. */
  salvando: string | null;
  /** A mensagem do backend, literal. A casca já a extraiu de `detail`/`error`. */
  erro: string | null;
}

/** Props do painel da aba "Onde está ativo" (`valeria-flow-channels.tsx`). */
export interface PainelCanaisProps {
  /** A versão escolhida no seletor da casca: é a que a ativação aponta. */
  flowId: FlowIdValeria;
}
