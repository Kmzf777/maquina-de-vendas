export type UserRole = "admin" | "vendedor";

// Rotas de página permitidas por role
export const ROLE_PAGES: Record<UserRole, string[]> = {
  admin: [
    "/dashboard",
    "/leads",
    "/conversas",
    "/campanhas",
    "/qualificacao",
    "/vendas",
    "/canais",
    "/estatisticas",
    "/config",
  ],
  vendedor: [
    "/dashboard",
    "/leads",
    "/conversas",
    "/campanhas",
    "/qualificacao",
    "/vendas",
  ],
};

// Prefixos de API route restritos a admin
export const ADMIN_API_PREFIXES = [
  "/api/channels",
  "/api/stats",
  "/api/agent-profiles",
  "/api/evolution",
  "/api/admin",
];

export function isAdminOnlyPage(pathname: string): boolean {
  const adminOnly = ["/canais", "/estatisticas", "/config"];
  return adminOnly.some((p) => pathname.startsWith(p));
}

export function isAdminOnlyApiRoute(pathname: string): boolean {
  return ADMIN_API_PREFIXES.some((prefix) => pathname.startsWith(prefix));
}
