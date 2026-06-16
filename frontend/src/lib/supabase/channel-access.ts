import { createClient as createServerClient } from "@/lib/supabase/server";
import type { getServiceSupabase } from "@/lib/supabase/api";

type ServiceSupabase = Awaited<ReturnType<typeof getServiceSupabase>>;

/**
 * Lançado quando NÃO é possível resolver a identidade do usuário logado
 * (falha transitória de auth/rede, sessão ausente, etc.).
 *
 * As rotas devem responder com status de erro (401) — NUNCA com lista vazia.
 * Devolver `[]` silenciosamente é indistinguível de "usuário não possui canais"
 * e faz a UI apagar a lista de conversas (a "tela em branco" relatada).
 */
export class ChannelAccessError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ChannelAccessError";
  }
}

/**
 * Retorna os `channel_id` que o usuário logado pode ver.
 *
 * - `null`     => sem restrição (admin) — vê todos os canais.
 * - `string[]` => restrito a esses canais. Lista vazia = não possui nenhum
 *                 canal (resultado legitimamente vazio, NÃO um erro).
 *
 * Lança {@link ChannelAccessError} se a autenticação falhar. Isso separa
 * "falha de auth" (transitória → o chamador devolve erro e a UI mantém o
 * estado anterior) de "usuário sem canais" (vazio legítimo). Sem essa
 * distinção, qualquer soluço de auth zerava a lista de conversas.
 */
export async function getAllowedChannelIds(
  supabase: ServiceSupabase,
): Promise<string[] | null> {
  let userId: string | undefined;
  let role: string | undefined;
  try {
    const userClient = await createServerClient();
    const { data, error } = await userClient.auth.getUser();
    if (error) throw error;
    userId = data.user?.id;
    role = data.user?.app_metadata?.role as string | undefined;
  } catch (err) {
    throw new ChannelAccessError(
      `auth check failed: ${err instanceof Error ? err.message : String(err)}`,
    );
  }

  // Sem usuário autenticado: fail-closed como erro — nunca exibir tudo (vazamento)
  // nem devolver [] silencioso (apaga a UI).
  if (!userId) {
    throw new ChannelAccessError("no authenticated user");
  }

  // Admin vê tudo, sem restrição.
  if (role === "admin") return null;

  // Vendedor: apenas os canais que possui.
  const { data: ownedChannels, error } = await supabase
    .from("channels")
    .select("id")
    .eq("owner_user_id", userId);
  if (error) {
    throw new ChannelAccessError(`failed to load owned channels: ${error.message}`);
  }
  return (ownedChannels || []).map((c: { id: string }) => c.id);
}
