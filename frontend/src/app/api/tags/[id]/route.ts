import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { TAG_DEBITO_VENCIDO_ID } from "@/lib/constants";

// A tag fixa de inadimplência é contrato do modal de disparo: se alguém a
// renomear ou apagar pela UI, o aviso de débito vencido some em silêncio —
// o pior modo de falha possível para um alerta.
const TAG_FIXA_ERRO =
  "A tag \"Débito vencido\" é fixa: o modal de criação de disparo depende dela " +
  "para avisar sobre leads inadimplentes.";

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  if (id === TAG_DEBITO_VENCIDO_ID) {
    return NextResponse.json({ error: TAG_FIXA_ERRO }, { status: 409 });
  }
  const supabase = await getServiceSupabase();
  const { name, color } = await request.json();

  const { data, error } = await supabase
    .from("tags")
    .update({ name, color })
    .eq("id", id)
    .select()
    .single();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json(data);
}

export async function DELETE(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  if (id === TAG_DEBITO_VENCIDO_ID) {
    return NextResponse.json({ error: TAG_FIXA_ERRO }, { status: 409 });
  }
  const supabase = await getServiceSupabase();

  const { error } = await supabase
    .from("tags")
    .delete()
    .eq("id", id);

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({ ok: true });
}
