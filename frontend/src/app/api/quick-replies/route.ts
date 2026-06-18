// frontend/src/app/api/quick-replies/route.ts
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET() {
  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("quick_replies")
    .select("*")
    .order("title", { ascending: true });

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
  return NextResponse.json(data);
}

export async function POST(request: NextRequest) {
  const supabase = await getServiceSupabase();
  const { shortcut, title, content } = await request.json();

  if (!title?.trim() || !content?.trim()) {
    return NextResponse.json({ error: "title e content são obrigatórios" }, { status: 400 });
  }

  const { data, error } = await supabase
    .from("quick_replies")
    .insert({ shortcut: shortcut?.trim() || null, title: title.trim(), content })
    .select()
    .single();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
  return NextResponse.json(data, { status: 201 });
}
