import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { normalizePhoneBR } from "@/lib/phone";
import { findLeadByPhoneVariants } from "@/lib/lead-phone-lookup";
import { cepDigits } from "@/lib/bling-contact-form";
import { resolverSegmentoFase } from "@/lib/segmento";
import {
  ADDRESS_FIELDS,
  formatAddress,
  hasAddressChange,
  isAddressComplete,
  type BlingEnderecoResultado,
} from "@/lib/lead-address";

function backendUrl(): string {
  return (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000").replace(/\/+$/, "");
}

/** Só para falha de rede/timeout: o backend nem chegou a responder. */
const BLING_INDISPONIVEL: BlingEnderecoResultado = {
  status: "error",
  message: "Bling indisponível — tente salvar de novo",
};

/** Motivo de uma resposta de erro do backend (`message`, `detail` ou `error`). */
async function motivoDoErro(resp: Response): Promise<string> {
  const corpo = (await resp.json().catch(() => null)) as Record<string, unknown> | null;
  for (const chave of ["message", "detail", "error"]) {
    const v = corpo?.[chave];
    if (typeof v === "string" && v.trim()) return v.trim();
  }
  return `Backend respondeu ${resp.status} ao atualizar o Bling`;
}

/**
 * Pede ao backend que copie o endereço do lead para o(s) contato(s) vinculado(s)
 * no Bling. Nunca lança: falha vira `status: "error"` e o PATCH segue 200 — o
 * endereço já está salvo no CRM, só a cópia no ERP ficou pendente.
 */
async function sincronizarEnderecoNoBling(leadId: string): Promise<BlingEnderecoResultado> {
  try {
    const resp = await fetch(`${backendUrl()}/api/bling/contacts/address`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lead_id: leadId }),
      signal: AbortSignal.timeout(20000),
    });
    if (!resp.ok) return { status: "error", message: await motivoDoErro(resp) };
    return (await resp.json()) as BlingEnderecoResultado;
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
    .select("stage, phone, segmento")
    .eq("id", id)
    .single();

  // Segmento e fase separados (cartão b67f1c6b): `segmento` validado contra o enum;
  // `stage` só aceita fase. Tela antiga que manda o segmento em `stage` continua
  // funcionando (vira `segmento` + fase `qualificando`; "secretaria" vira `triagem`).
  const segmentoFase = resolverSegmentoFase(body);
  if (!segmentoFase.ok) {
    return NextResponse.json({ error: segmentoFase.erro }, { status: 400 });
  }
  delete body.stage;
  delete body.segmento;
  Object.assign(body, segmentoFase.campos);

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

  // Endereço estruturado (cartão b3788533): aparado, vazio vira null, CEP só
  // com dígitos e UF maiúscula — o mesmo formato que o Bling recebe.
  const mudouEndereco = hasAddressChange(body);
  if (mudouEndereco) {
    for (const campo of ADDRESS_FIELDS) {
      if (!(campo in body)) continue;
      let valor = typeof body[campo] === "string" ? body[campo].trim() : "";
      if (campo === "cep") valor = cepDigits(valor);
      if (campo === "uf") valor = valor.toUpperCase();
      body[campo] = valor || null;
    }
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

    // Gatilho stage_enter (fire-and-forget). Um disparo por campo que MUDOU, cada um
    // com só o seu valor: o filtro de segmento olha `segmento`, o de fase olha `stage`
    // (automation/triggers.py::_passes_filter).
    const mudancas: Record<string, string>[] = [];
    if (body.stage && body.stage !== currentLead.stage) mudancas.push({ stage: body.stage });
    if (body.segmento && body.segmento !== currentLead.segmento) mudancas.push({ segmento: body.segmento });
    for (const data of mudancas) {
      void fetch(`${backendUrl()}/api/automation/trigger`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ event_type: "stage_enter", lead_id: id, data }),
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
