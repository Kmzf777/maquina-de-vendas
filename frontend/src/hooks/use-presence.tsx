"use client";

import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  useMemo,
  type ReactNode,
} from "react";
import { usePathname } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import type { RealtimeChannel } from "@supabase/supabase-js";

export interface KnownUser {
  email: string;
  name: string;
  role: "admin" | "vendedor";
}

export const KNOWN_USERS: KnownUser[] = [
  { email: "arthur@cafecanastra.com", name: "Arthur", role: "vendedor" },
  { email: "rafael@cafecanastra.com", name: "Rafael", role: "admin"    },
  { email: "kelwin@cafecanastra.com", name: "Kelwin", role: "admin"    },
  { email: "joao@cafecanastra.com",   name: "João",   role: "vendedor" },
];

const KNOWN_USERS_MAP: Record<string, KnownUser> = Object.fromEntries(
  KNOWN_USERS.map((u) => [u.email, u])
);

export interface UserPresenceState {
  email: string;
  name: string;
  role: "admin" | "vendedor";
  status: "online" | "ausente" | "offline";
  page: string | null;
}

type PresencePayload = {
  email: string;
  name: string;
  role: string;
  page: string;
  status: "online" | "ausente";
};

const STATUS_ORDER: Record<UserPresenceState["status"], number> = {
  online: 0,
  ausente: 1,
  offline: 2,
};

function buildUserList(
  presenceState: Record<string, PresencePayload[]>
): UserPresenceState[] {
  const onlineMap = new Map<string, PresencePayload>();
  for (const entries of Object.values(presenceState)) {
    for (const entry of entries) {
      if (entry.email) onlineMap.set(entry.email, entry);
    }
  }

  return KNOWN_USERS.map((known): UserPresenceState => {
    const presence = onlineMap.get(known.email);
    if (presence) {
      return {
        email: known.email,
        name: known.name,
        role: known.role,
        status: presence.status === "ausente" ? "ausente" : "online",
        page: presence.page ?? null,
      };
    }
    return { email: known.email, name: known.name, role: known.role, status: "offline", page: null };
  }).sort((a, b) => STATUS_ORDER[a.status] - STATUS_ORDER[b.status]);
}

interface PresenceContextValue {
  users: UserPresenceState[];
  loading: boolean;
}

const PresenceContext = createContext<PresenceContextValue>({
  users: [],
  loading: true,
});

/**
 * Owns the single "crm-presence" Realtime channel.
 * Handles both reading (presence state) and writing (tracking current user).
 * Must wrap all authenticated content so consumers can call usePresence().
 */
export function PresenceProvider({ children }: { children: ReactNode }) {
  const supabase = useMemo(() => createClient(), []);
  const pathname = usePathname();
  const [users, setUsers] = useState<UserPresenceState[]>([]);
  const [loading, setLoading] = useState(true);
  const channelRef = useRef<RealtimeChannel | null>(null);
  const payloadRef = useRef<{
    email: string;
    name: string;
    role: string;
    page: string;
    status: "online" | "ausente";
  } | null>(null);

  // Create ONE channel, register all handlers before subscribing.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    let cancelled = false;

    async function init() {
      const { data } = await supabase.auth.getSession();
      if (cancelled) return;

      const email = data.session?.user?.email;
      const known = email ? KNOWN_USERS_MAP[email] : null;

      if (known && email) {
        payloadRef.current = {
          email,
          name: known.name,
          role: known.role,
          page: pathname,
          status: "online",
        };
      }

      const channel = supabase.channel("crm-presence");
      channelRef.current = channel;

      channel
        .on("presence", { event: "sync" }, () => {
          const state = channel.presenceState() as Record<string, PresencePayload[]>;
          setUsers(buildUserList(state));
          setLoading(false);
        })
        .on("presence", { event: "join" }, () => {
          const state = channel.presenceState() as Record<string, PresencePayload[]>;
          setUsers(buildUserList(state));
          setLoading(false);
        })
        .on("presence", { event: "leave" }, () => {
          const state = channel.presenceState() as Record<string, PresencePayload[]>;
          setUsers(buildUserList(state));
        })
        .subscribe((status) => {
          if (status === "SUBSCRIBED" && payloadRef.current && !cancelled) {
            channel.track(payloadRef.current);
          }
        });
    }

    init();

    return () => {
      cancelled = true;
      if (channelRef.current) {
        supabase.removeChannel(channelRef.current);
        channelRef.current = null;
      }
    };
  }, []);

  // Keep tracked page in sync with navigation
  useEffect(() => {
    if (!payloadRef.current || !channelRef.current) return;
    payloadRef.current = { ...payloadRef.current, page: pathname };
    channelRef.current.track(payloadRef.current);
  }, [pathname]);

  // Track tab visibility
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

  return (
    <PresenceContext.Provider value={{ users, loading }}>
      {children}
    </PresenceContext.Provider>
  );
}

export function usePresence() {
  return useContext(PresenceContext);
}
