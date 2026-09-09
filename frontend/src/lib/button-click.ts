/**
 * Distingue "o lead TOCOU no botão X" de "o lead DIGITOU X".
 *
 * Até 2026-09 os dois eram a mesma coisa na tela: `meta_parser.py` achatava o clique em
 * `parsed_type='text'` e guardava só o rótulo, então as 98 mensagens de clique que existem
 * em produção estão gravadas como texto puro (`message_type=NULL`, `metadata=NULL`) e caem
 * no parágrafo genérico da bolha (message-bubble.tsx:524). O operador lia "Nao tenho
 * interesse" sem saber se aquilo foi um toque no menu ou uma frase.
 *
 * Agora o parser preserva o clique (`parsed_type='button'` + `metadata.payload/title`,
 * backend/app/webhook/meta_parser.py:138-163) e esta função é o único ponto que lê esse
 * sinal. Mensagens antigas continuam sem `message_type` e seguem renderizando como texto —
 * não há como reconstituí-las, e inventar um chip para elas seria mentir.
 */
export interface ButtonClick {
  /** Rótulo que o lead viu no botão. */
  title: string;
  /**
   * id/payload do botão, e só quando difere do rótulo: em quick reply de TEMPLATE a Meta
   * devolve payload = texto do botão, e repetir isso na tela é ruído.
   */
  payload: string | null;
}

function texto(valor: unknown): string {
  return typeof valor === "string" ? valor.trim() : "";
}

export function readButtonClick(message: {
  message_type?: string | null;
  content?: string | null;
  metadata?: Record<string, unknown> | null;
}): ButtonClick | null {
  if (message.message_type !== "button") return null;

  // `metadata` é jsonb: pode chegar escalar, array ou null. Acesso defensivo, sem cast.
  const meta = (message.metadata ?? {}) as Record<string, unknown>;
  const title = texto(meta.title) || texto(message.content);
  if (!title) return null;

  const payload = texto(meta.payload);
  return { title, payload: payload && payload !== title ? payload : null };
}
