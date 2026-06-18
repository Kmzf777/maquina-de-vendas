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
