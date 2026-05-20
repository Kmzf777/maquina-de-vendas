"use client";

import { useState, useEffect, useCallback } from "react";
import type { Sale } from "@/lib/types";

export interface SalesFilters {
  from?: string;
  to?: string;
  soldBy?: string;
  search?: string;
  page?: number;
}

export function useSales(filters: SalesFilters = {}) {
  const [sales, setSales] = useState<Sale[]>([]);
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(true);

  const fetchSales = useCallback(async () => {
    setLoading(true);
    const params = new URLSearchParams();
    if (filters.from) params.set("from", filters.from);
    if (filters.to) params.set("to", filters.to);
    if (filters.soldBy) params.set("sold_by", filters.soldBy);
    if (filters.search) params.set("search", filters.search);
    if (filters.page) params.set("page", String(filters.page));
    const res = await fetch(`/api/sales?${params}`);
    if (res.ok) {
      const { data, count: c } = await res.json();
      setSales(data ?? []);
      setCount(c ?? 0);
    }
    setLoading(false);
  }, [filters.from, filters.to, filters.soldBy, filters.search, filters.page]);

  useEffect(() => { fetchSales(); }, [fetchSales]);

  return { sales, count, loading, refetch: fetchSales };
}
