"use client";

import { useEffect, useRef, useMemo } from "react";
import { usePathname } from "next/navigation";
import { createClient } from "@/lib/supabase/client";

const KNOWN_USERS: Record<string, { name: string; role: string }> = {
  "arthur@cafecanastra.com": { name: "Arthur", role: "vendedor" },
  "rafael@cafecanastra.com": { name: "Rafael", role: "admin" },
  "kelwin@cafecanastra.com": { name: "Kelwin", role: "admin" },
  "joao@cafecanastra.com":   { name: "João",   role: "vendedor" },
};

/**
 * Side-effect-only hook. Mounts the Supabase Presence tracker for the
 * current authenticated user. Call this once from AuthenticatedShell.
 *
 * - Tracks page on every navigation (pathname change)
 * - Tracks status "ausente" when tab is hidden, "online" when visible
 */
export function usePresenceTracker() {
  const supabase = useMemo(() => createClient(), []);
  const pathname = usePathname();

  // Persist refs so the visibility handler and pathname effect share state
  const channelRef = useRef<ReturnType<typeof supabase.channel> | null>(null);
  const payloadRef = useRef<{
    email: string;
    name: string;
    role: string;
    page: string;
    status: "online" | "ausente";
  } | null>(null);

  // Mount: initialise channel once
  useEffect(() => {
    async function init() {
      const { data } = await supabase.auth.getSession();
      const email = data.session?.user?.email;
      if (!email) return;

      const known = KNOWN_USERS[email];
      if (!known) return;

      payloadRef.current = {
        email,
        name: known.name,
        role: known.role,
        page: pathname,
        status: "online",
      };

      const ch = supabase.channel("crm-presence");
      channelRef.current = ch;

      ch.subscribe((status) => {
        if (status === "SUBSCRIBED" && payloadRef.current) {
          ch.track(payloadRef.current);
        }
      });
    }

    init();

    return () => {
      if (channelRef.current) {
        supabase.removeChannel(channelRef.current);
        channelRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // mount only

  // Update page whenever pathname changes
  useEffect(() => {
    if (!payloadRef.current || !channelRef.current) return;
    payloadRef.current = { ...payloadRef.current, page: pathname };
    channelRef.current.track(payloadRef.current);
  }, [pathname]);

  // Handle tab visibility
  useEffect(() => {
    const handleVisibility = () => {
      if (!payloadRef.current || !channelRef.current) return;
      const status = document.hidden ? "ausente" : "online";
      payloadRef.current = { ...payloadRef.current, status };
      channelRef.current.track(payloadRef.current);
    };

    document.addEventListener("visibilitychange", handleVisibility);
    return () => document.removeEventListener("visibilitychange", handleVisibility);
  }, []);
}
