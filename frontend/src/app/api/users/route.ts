import { NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET() {
  const supabase = await getServiceSupabase();
  const { data: { users }, error } = await supabase.auth.admin.listUsers();
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(
    users.map((u) => ({
      id: u.id,
      email: u.email ?? "",
      name: (u.user_metadata?.full_name as string | undefined) ?? u.email ?? "",
      role: (u.app_metadata?.role as string | undefined) ?? "vendedor",
    }))
  );
}
