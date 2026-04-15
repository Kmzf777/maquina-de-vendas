import { AuthenticatedShell } from "@/components/authenticated-shell";

export const dynamic = "force-dynamic";

export default function AuthenticatedLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <AuthenticatedShell>{children}</AuthenticatedShell>;
}
