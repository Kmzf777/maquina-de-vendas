import { createClient as createServerClient } from "@/lib/supabase/server";

/** Retorna { ok } ou { error, status } se o chamador não for admin. */
export async function requireAdmin(): Promise<
  { ok: true } | { ok: false; error: string; status: number }
> {
  const supabase = await createServerClient();
  const {
    data: { user },
    error,
  } = await supabase.auth.getUser();

  if (error || !user) return { ok: false, error: "Não autenticado", status: 401 };
  if (user.app_metadata?.role !== "admin")
    return { ok: false, error: "Permissão insuficiente", status: 403 };
  return { ok: true };
}
