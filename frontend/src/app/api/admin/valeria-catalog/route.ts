/**
 * Preços que a ValerIA oferta (tabela `products`). Só admin. O backend relê o
 * catálogo a cada 60 s (`backend/app/agent/catalog.py`), então o valor salvo aqui
 * vira a oferta da ValerIA em até 1 minuto, no prompt e no `calcular_orcamento`.
 */
import { NextRequest, NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { requireAdmin } from "@/lib/admin-auth";
import {
  formatPrecoCatalogo,
  parsePrecoCatalogo,
  precoValido,
  type CatalogItem,
} from "@/lib/valeria-catalog";

const COLUNAS_LEITURA = "id,sector,name,price_formatted";
// O upsert repete a linha inteira: INSERT ... ON CONFLICT checa NOT NULL antes do
// conflito, então mandar só {id, price_formatted} quebraria em `name`/`sector`.
const COLUNAS_LINHA = "id,sector,name,price_formatted,min_lot,description,image_urls,is_active";

interface LinhaLeitura {
  id: string;
  sector: string;
  name: string;
  price_formatted: string | null;
}

function paraItem(r: LinhaLeitura): CatalogItem {
  return {
    id: r.id,
    sector: r.sector,
    name: r.name,
    price_formatted: r.price_formatted,
    preco: parsePrecoCatalogo(r.price_formatted),
  };
}

export async function GET() {
  const gate = await requireAdmin();
  if (!gate.ok) return NextResponse.json({ error: gate.error }, { status: gate.status });

  const sb = await getServiceSupabase();
  const { data, error } = await sb
    .from("products")
    .select(COLUNAS_LEITURA)
    .eq("is_active", true)
    .order("sector")
    .order("name");
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ data: ((data ?? []) as LinhaLeitura[]).map(paraItem) });
}

export async function PATCH(req: NextRequest) {
  const gate = await requireAdmin();
  if (!gate.ok) return NextResponse.json({ error: gate.error }, { status: gate.status });

  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "JSON inválido" }, { status: 400 });
  }

  const itens = (body as { itens?: unknown })?.itens;
  if (!Array.isArray(itens) || itens.length === 0) {
    return NextResponse.json({ error: "Nenhum preço para salvar" }, { status: 400 });
  }

  const precoPorId = new Map<string, number>();
  for (const item of itens as { id?: unknown; preco?: unknown }[]) {
    if (typeof item?.id !== "string" || item.id === "") {
      return NextResponse.json({ error: "Item sem id" }, { status: 400 });
    }
    if (!precoValido(item.preco)) {
      return NextResponse.json({ error: `Preço inválido para ${item.id}` }, { status: 400 });
    }
    if (precoPorId.has(item.id)) {
      return NextResponse.json({ error: `Produto repetido: ${item.id}` }, { status: 400 });
    }
    precoPorId.set(item.id, item.preco);
  }
  const ids = [...precoPorId.keys()];

  const sb = await getServiceSupabase();
  const { data: linhas, error: erroLeitura } = await sb
    .from("products")
    .select(COLUNAS_LINHA)
    .in("id", ids)
    .eq("is_active", true);
  if (erroLeitura) return NextResponse.json({ error: erroLeitura.message }, { status: 500 });
  if ((linhas ?? []).length !== ids.length) {
    return NextResponse.json({ error: "Produto não encontrado ou inativo" }, { status: 404 });
  }

  const agora = new Date().toISOString();
  const payload = (linhas as Record<string, unknown>[]).map((linha) => ({
    ...linha,
    price_formatted: formatPrecoCatalogo(precoPorId.get(linha.id as string)!),
    updated_at: agora,
  }));

  // Um único upsert = uma instrução só no Postgres: grava tudo ou nada.
  const { data, error } = await sb
    .from("products")
    .upsert(payload, { onConflict: "id" })
    .select(COLUNAS_LEITURA);
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ data: ((data ?? []) as LinhaLeitura[]).map(paraItem) });
}
