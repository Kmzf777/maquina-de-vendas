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
    "/painel-vendas",
    "/canais",
    "/estatisticas",
    "/trafego",
    "/config",
  ],
  vendedor: [
    "/dashboard",
    "/leads",
    "/conversas",
    "/campanhas",
    "/qualificacao",
    "/vendas",
    "/painel-vendas",
  ],
};

// Prefixos de API route restritos a admin
export const ADMIN_API_PREFIXES = [
  "/api/stats",
  "/api/admin",
  "/api/users",
  "/api/model-pricing",
  "/api/lp-webhook",
  "/api/traffic",
];

export function isAdminOnlyPage(pathname: string): boolean {
  const adminOnly = ROLE_PAGES.admin.filter(
    (p) => !ROLE_PAGES.vendedor.includes(p)
  );
  return adminOnly.some((p) => pathname.startsWith(p));
}

export function isAdminOnlyApiRoute(pathname: string): boolean {
  return ADMIN_API_PREFIXES.some((prefix) => pathname.startsWith(prefix));
}
