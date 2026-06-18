import { createClient as createServerClient } from "@/lib/supabase/server";
import type { getServiceSupabase } from "@/lib/supabase/api";

type ServiceSupabase = Awaited<ReturnType<typeof getServiceSupabase>>;
type Guard = { ok: true } | { ok: false; error: string; status: number };

export interface CurrentUser {
  userId: string;
  role: string | undefined;
}

export interface PipelineOwnership {
  owner_user_id: string | null;
  is_universal: boolean;
}

/** Mover/criar DEALS no funil: admin OU dono OU universal. */
export function canWriteDealsInPipeline(user: CurrentUser, p: PipelineOwnership): boolean {
  return user.role === "admin" || p.is_universal || p.owner_user_id === user.userId;
}

/** Gerenciar a ESTRUTURA do funil (renomear, stages, excluir, trocar dono): admin OU dono. */
export function canManagePipeline(user: CurrentUser, p: PipelineOwnership): boolean {
  return user.role === "admin" || p.owner_user_id === user.userId;
}

/** Dono ao criar: vendedor → sempre ele mesmo; admin → o solicitado (null = administrativo). */
export function resolvePipelineOwnerOnCreate(
  user: CurrentUser,
  requestedOwnerId: string | null | undefined,
): string | null {
  if (user.role === "admin") return requestedOwnerId ?? null;
  return user.userId;
}

/** Lançado quando não é possível resolver a identidade do usuário logado. */
export class PipelineAccessError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PipelineAccessError";
  }
}

/** Resolve o usuário logado a partir dos cookies (fail-closed). */
export async function getCurrentUser(): Promise<CurrentUser> {
  try {
    const userClient = await createServerClient();
    const { data, error } = await userClient.auth.getUser();
    if (error) throw error;
    const userId = data.user?.id;
    if (!userId) throw new Error("no authenticated user");
    return { userId, role: data.user?.app_metadata?.role as string | undefined };
  } catch (err) {
    throw new PipelineAccessError(
      `auth check failed: ${err instanceof Error ? err.message : String(err)}`,
    );
  }
}

async function assertWith(
  supabase: ServiceSupabase,
  pipelineId: string,
  predicate: (u: CurrentUser, p: PipelineOwnership) => boolean,
): Promise<Guard> {
  let user: CurrentUser;
  try {
    user = await getCurrentUser();
  } catch {
    return { ok: false, error: "Não autenticado", status: 401 };
  }
  const { data, error } = await supabase
    .from("pipelines")
    .select("owner_user_id, is_universal")
    .eq("id", pipelineId)
    .maybeSingle();
  if (error) return { ok: false, error: error.message, status: 500 };
  if (!data) return { ok: false, error: "Funil não encontrado.", status: 404 };
  if (!predicate(user, data as PipelineOwnership)) {
    return { ok: false, error: "Permissão insuficiente para este funil.", status: 403 };
  }
  return { ok: true };
}

/** Guarda para gestão de estrutura (renomear, stages, excluir, trocar dono). */
export function assertCanManagePipeline(supabase: ServiceSupabase, pipelineId: string) {
  return assertWith(supabase, pipelineId, canManagePipeline);
}

/** Guarda para escrita de deals no funil. */
export function assertCanWriteDealsInPipeline(supabase: ServiceSupabase, pipelineId: string) {
  return assertWith(supabase, pipelineId, canWriteDealsInPipeline);
}

/**
 * IDs de funis que o usuário pode ver. null = admin (sem restrição).
 * Vendedor → próprios + universais. Lança PipelineAccessError se auth falhar.
 */
export async function getAllowedPipelineIds(
  supabase: ServiceSupabase,
): Promise<string[] | null> {
  const { userId, role } = await getCurrentUser();
  if (role === "admin") return null;
  const { data, error } = await supabase
    .from("pipelines")
    .select("id")
    .or(`owner_user_id.eq.${userId},is_universal.eq.true`);
  if (error) throw new PipelineAccessError(`failed to load pipelines: ${error.message}`);
  return (data || []).map((p: { id: string }) => p.id);
}
