import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { normalizePhoneBR } from "@/lib/phone";
import { findLeadByPhoneVariants } from "@/lib/lead-phone-lookup";
import { cepDigits } from "@/lib/bling-contact-form";
import { formatAddress, hasAddressChange, isAddressComplete } from "@/lib/lead-address";

function backendUrl(): string {
  return (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000").replace(/\/+$/, "");
}

/** Resultado da atualização do endereço no Bling, devolvido junto do lead. */
type BlingEndereco = { status: string; message?: string; contas?: unknown[] };

const BLING_INDISPONIVEL: BlingEndereco = {
  status: "error",
  message: "Bling indisponível — tente salvar de novo",
};

/**
 * Pede ao backend que copie o endereço do lead para o(s) contato(s) vinculado(s)
 * no Bling. Nunca lança: falha vira `status: "error"` e o PATCH segue 200 — o
 * endereço já está salvo no CRM, só a cópia no ERP ficou pendente.
 */
async function sincronizarEnderecoNoBling(leadId: string): Promise<BlingEndereco> {
  try {
    const resp = await fetch(`${backendUrl()}/api/bling/contacts/address`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lead_id: leadId }),
      signal: AbortSignal.timeout(20000),
    });
    if (!resp.ok) return BLING_INDISPONIVEL;
    return (await resp.json()) as BlingEndereco;
  } catch {
    return BLING_INDISPONIVEL;
  }
}

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();
  const body = await request.json();

  const { data: currentLead } = await supabase
    .from("leads")
    .select("stage, phone")
    .eq("id", id)
    .single();

  // Telefone: grava o canônico e recusa número que outro lead já usa em
  // qualquer formato antigo (cartão b747da43).
  if (body.phone !== undefined) {
    const texto = typeof body.phone === "string" ? body.phone : "";
    const canonical = normalizePhoneBR(texto);
    if (!canonical) {
      const n = texto.replace(/\D/g, "").length;
      return NextResponse.json(
        { error: `Telefone inválido: ${n} dígito(s). Use DDD + número (ex.: 34 99999-9999)` },
        { status: 422 },
      );
    }
    // Mesmo número do próprio lead (só mudou o formato): não há conflito a checar.
    const mesmoNumero = !!currentLead?.phone && normalizePhoneBR(currentLead.phone) === canonical;
    let outro = null;
    if (!mesmoNumero) {
      try {
        outro = await findLeadByPhoneVariants(supabase, canonical, id);
      } catch (err) {
        return NextResponse.json({ error: err instanceof Error ? err.message : String(err) }, { status: 500 });
      }
    }
    if (outro) {
      return NextResponse.json(
        { error: `Outro lead já usa este telefone: ${outro.name || outro.phone}`, lead: outro },
        { status: 409 },
      );
    }
    body.phone = canonical;
  }

  // Endereço estruturado (cartão b3788533): CEP só com dígitos e UF maiúscula,
  // no mesmo formato que o Bling recebe.
  const mudouEndereco = hasAddressChange(body);
  if (mudouEndereco) {
    if ("cep" in body) body.cep = cepDigits(typeof body.cep === "string" ? body.cep : "") || null;
    if ("uf" in body && typeof body.uf === "string") body.uf = body.uf.trim().toUpperCase();
  }

  const { data, error } = await supabase
    .from("leads")
    .update(body)
    .eq("id", id)
    .select()
    .single();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  if (currentLead) {
    const events = [];
    if (body.stage && body.stage !== currentLead.stage) {
      events.push({
        lead_id: id,
        event_type: "stage_change",
        old_value: currentLead.stage,
        new_value: body.stage,
      });
    }
    if (events.length > 0) {
      await supabase.from("lead_events").insert(events);
    }

    // Fire automation trigger for stage_enter (fire-and-forget)
    if (body.stage && body.stage !== currentLead.stage) {
      void fetch(`${backendUrl()}/api/automation/trigger`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          event_type: "stage_enter",
          lead_id: id,
          data: { stage: body.stage },
        }),
      }).catch(() => {});
    }
  }

  if (mudouEndereco && data) {
    // O texto livre `endereco` (legado, lido por telas e pelo agente) passa a
    // espelhar os campos estruturados. Todos vazios → `formatAddress` dá null
    // e o texto antigo fica como estava.
    const formatado = formatAddress(data);
    if (formatado && formatado !== data.endereco) {
      const { error: erroTexto } = await supabase
        .from("leads")
        .update({ endereco: formatado })
        .eq("id", id);
      if (!erroTexto) data.endereco = formatado;
    }
    const bling_endereco = isAddressComplete(data)
      ? await sincronizarEnderecoNoBling(id)
      : { status: "incomplete" };
    return NextResponse.json({ ...data, bling_endereco });
  }

  return NextResponse.json(data);
}

export async function DELETE(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();

  const { data: lead } = await supabase.from("leads").select("id").eq("id", id).single();
  if (!lead) return NextResponse.json({ error: "Lead not found" }, { status: 404 });

  await supabase.from("follow_up_jobs").delete().eq("lead_id", id);
  await supabase.from("campaign_enrollments").delete().eq("lead_id", id);
  await supabase.from("broadcast_leads").delete().eq("lead_id", id);
  await supabase.from("deals").delete().eq("lead_id", id);
  await supabase.from("lead_tags").delete().eq("lead_id", id);
  await supabase.from("token_usage").delete().eq("lead_id", id);
  await supabase.from("messages").delete().eq("lead_id", id);
  await supabase.from("conversations").delete().eq("lead_id", id);
  await supabase.from("leads").delete().eq("id", id);

  return NextResponse.json({ deleted: true, lead_id: id });
}
