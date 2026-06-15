"""
READ-ONLY diagnostic for the SLA "Em atraso agora" bug.

Replicates EXACTLY the frontend overdue computation (use-overdue-leads.ts +
sla-rounds.ts walkConversation, restricted to sent_by IN ('user','seller')),
then cross-checks each flagged conversation against the TRUE last message
across ALL sent_by values to reveal false positives.

No writes. SELECT only.
"""
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from supabase import create_client

# Root .env (production config — read-only use here)
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
load_dotenv(os.path.join(ROOT, ".env"))

URL = os.environ["SUPABASE_URL"]
KEY = os.environ["SUPABASE_SERVICE_KEY"]
sb = create_client(URL, KEY)

SP = timezone(timedelta(hours=-3))  # America/Sao_Paulo fixed UTC-3 (no DST)


def parse_ts(s):
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def sp_date_str(dt_utc):
    loc = dt_utc.astimezone(SP)
    return f"{loc.year:04d}-{loc.month:02d}-{loc.day:02d}"


def business_minutes_between(frm, to, start_min, end_min, weekdays, excluded):
    """Faithful port of business-hours.ts businessMinutesBetween (fixed UTC-3)."""
    if frm >= to:
        return 0.0
    total = 0.0
    cur = frm.astimezone(SP)
    end_loc = to.astimezone(SP)
    # iterate calendar days in SP
    day = cur.replace(hour=0, minute=0, second=0, microsecond=0)
    while day <= end_loc:
        js_weekday = (day.weekday() + 1) % 7  # Python Mon=0 -> JS Sun=0
        date_str = f"{day.year:04d}-{day.month:02d}-{day.day:02d}"
        if js_weekday in weekdays and date_str not in excluded:
            biz_start = day + timedelta(minutes=start_min)
            biz_end = day + timedelta(minutes=end_min)
            eff_start = max(cur, biz_start)
            eff_end = min(end_loc, biz_end)
            if eff_end > eff_start:
                total += (eff_end - eff_start).total_seconds() / 60.0
        day = day + timedelta(days=1)
    return total


def walk_conversation(all_msgs, closers, last_seller_response_at, now, win):
    """Generalized walkConversation: a round closes when a msg whose sent_by is in
    `closers` arrives. `all_msgs` must already be filtered to the senders we feed in.
    Returns open-round elapsed business minutes, or None."""
    start_min, end_min, weekdays, excluded = win
    wait_start = None
    for m in all_msgs:
        sb_ = m["sent_by"]
        if sb_ == "user":
            if wait_start is None:
                wait_start = m["created_at"]
        elif sb_ in closers:
            wait_start = None
    if wait_start is not None:
        fin = last_seller_response_at
        if fin and fin > wait_start:
            return None
        return business_minutes_between(
            parse_ts(wait_start), now, start_min, end_min, weekdays, excluded
        )
    return None


def fetch_all(table, select, filters=None, order=None, asc=True):
    PAGE = 1000
    out = []
    off = 0
    while True:
        q = sb.table(table).select(select)
        if filters:
            for f in filters:
                q = f(q)
        if order:
            q = q.order(order, desc=not asc)
        q = q.range(off, off + PAGE - 1)
        data = q.execute().data or []
        out.extend(data)
        if len(data) < PAGE:
            break
        off += PAGE
    return out


def main():
    cfgs = sb.table("sla_seller_config").select("*").eq("active", True).execute().data or []
    overrides = sb.table("sla_overrides").select("user_id, start_date, end_date").execute().data or []
    settings = sb.table("sla_settings").select("target_minutes").eq("id", 1).single().execute().data
    target = (settings or {}).get("target_minutes", 20)

    print(f"== SLA configs ativas: {len(cfgs)} | target={target}min ==")
    for c in cfgs:
        print(f"   - {c['display_name']!r} channel={c['channel_id']} "
              f"win={c['window_start_minute']}-{c['window_end_minute']} wd={c['active_weekdays']}")

    def excluded_for(user_id):
        out = set()
        for o in overrides:
            if o["user_id"] is not None and o["user_id"] != user_id:
                continue
            s = datetime.fromisoformat(o["start_date"] + "T12:00:00+00:00")
            e = datetime.fromisoformat(o["end_date"] + "T12:00:00+00:00")
            d = s
            while d <= e:
                out.add(sp_date_str(d))
                d = d + timedelta(days=1)
        return out

    channel_ids = [c["channel_id"] for c in cfgs]
    if not channel_ids:
        print("Sem canais. Fim.")
        return

    # conversations for these channels
    convs = fetch_all(
        "conversations",
        "id, channel_id, lead_id, last_seller_response_at",
        filters=[lambda q: q.in_("channel_id", channel_ids)],
        order="created_at", asc=False,
    )
    conv_ids = [c["id"] for c in convs]
    print(f"\n== Conversas nos canais SLA: {len(convs)} ==")

    # ALL messages (every sent_by) for these conversations, chronological
    msgs_by_conv = defaultdict(list)
    CHUNK = 150
    for i in range(0, len(conv_ids), CHUNK):
        slice_ids = conv_ids[i:i + CHUNK]
        off = 0
        PAGE = 1000
        while True:
            data = (
                sb.table("messages")
                .select("conversation_id, sent_by, created_at")
                .in_("conversation_id", slice_ids)
                .order("created_at", desc=False)
                .range(off, off + PAGE - 1)
                .execute().data or []
            )
            for m in data:
                msgs_by_conv[m["conversation_id"]].append(m)
            if len(data) < PAGE:
                break
            off += PAGE

    now = datetime.now(timezone.utc)
    cfg_by_channel = {c["channel_id"]: c for c in cfgs}

    # Closer sets for the three interpretations
    CUR = {"seller"}                                              # current (buggy)
    REPLY = {"seller", "agent"}                                   # Fork B: genuine replies
    ANY_OUR = {"seller", "agent", "followup", "broadcast",
               "campaign", "automation", "handoff", "handoff_context"}  # Fork A

    # global tallies
    overdue_total = 0
    overdue_forkB = 0
    overdue_forkA = 0
    true_last_sender_counter = Counter()       # among CURRENT overdue: sent_by of TRUE last msg
    false_overdue = 0
    genuine_open_user_last = 0
    sent_by_global = Counter()
    examples = []
    forkb_examples = []
    forkb_last_sender = Counter()  # entre os que PERMANECEM no fix: quem foi o último real

    for c in convs:
        ch = c["channel_id"]
        cfg = cfg_by_channel.get(ch)
        if not cfg:
            continue
        win = (
            cfg["window_start_minute"],
            cfg["window_end_minute"],
            set(cfg["active_weekdays"]),
            excluded_for(cfg["user_id"]),
        )
        all_msgs = msgs_by_conv.get(c["id"], [])
        for m in all_msgs:
            sent_by_global[m["sent_by"]] += 1
        lsra = c["last_seller_response_at"]

        # CURRENT logic: only user/seller fed in, only seller closes
        us_msgs = [m for m in all_msgs if m["sent_by"] in ("user", "seller")]
        elapsed = walk_conversation(us_msgs, CUR, lsra, now, win)

        # Fork B (= FIX implementado): feed user + replies; seller+agent close
        b_msgs = [m for m in all_msgs if m["sent_by"] == "user" or m["sent_by"] in REPLY]
        e_b = walk_conversation(b_msgs, REPLY, lsra, now, win)
        if e_b is not None and e_b > target:
            overdue_forkB += 1
            forkb_last_sender[all_msgs[-1]["sent_by"] if all_msgs else "(none)"] += 1
            if len(forkb_examples) < 20:
                tail = [(mm["sent_by"], mm["created_at"]) for mm in all_msgs[-5:]]
                forkb_examples.append({
                    "conv": c["id"], "elapsed": round(e_b), "tail": tail,
                })

        # FIX REAL (impl shipada): cliente-facing = tudo menos nota interna (handoff_context);
        # seller/agent fecham e contam; disparo ignora; suprime atraso se a ÚLTIMA
        # mensagem cliente-facing NÃO for do cliente (nós falamos por último).
        cf = [m for m in all_msgs if m["sent_by"] != "handoff_context"]
        wait = None
        for m in cf:
            if m["sent_by"] == "user":
                if wait is None:
                    wait = m["created_at"]
            elif m["sent_by"] in REPLY:
                wait = None
        e_a = None
        if wait is not None and not (lsra and lsra > wait):
            last = cf[-1] if cf else None
            if not (last and last["sent_by"] != "user"):
                sm, em, wd, ex = win
                e_a = business_minutes_between(parse_ts(wait), now, sm, em, wd, ex)
        if e_a is not None and e_a > target:
            overdue_forkA += 1

        if elapsed is None or elapsed <= target:
            continue
        overdue_total += 1
        true_last = all_msgs[-1] if all_msgs else None
        tl_sender = true_last["sent_by"] if true_last else "(no-msgs)"
        true_last_sender_counter[tl_sender] += 1
        if tl_sender == "user":
            genuine_open_user_last += 1
        else:
            false_overdue += 1
            if len(examples) < 12:
                tail = [(mm["sent_by"], mm["created_at"]) for mm in all_msgs[-4:]]
                examples.append({
                    "conv": c["id"],
                    "vendedor": cfg["display_name"],
                    "elapsed": round(elapsed),
                    "true_last_sender": tl_sender,
                    "tail": tail,
                    "last_seller_response_at": lsra,
                })

    print(f"\n== sent_by distribution (todas as msgs nos canais SLA) ==")
    for k, v in sent_by_global.most_common():
        print(f"   {k:18s} {v}")

    print(f"\n========== RESULTADO ==========")
    print(f"Total marcado como OVERDUE pelo dashboard (ATUAL, só 'seller' fecha): {overdue_total}")
    print(f"  -> TRUE last message é do CLIENTE (user)        : {genuine_open_user_last}")
    print(f"  -> TRUE last message é do NOSSO LADO (FALSO ATRASO): {false_overdue}")
    print(f"\nOverdue sob FORK B = FIX ATUAL (seller+agent fecham, broadcast/followup NÃO): {overdue_forkB}")
    print(f"  Quebra do ÚLTIMO remetente real desses {overdue_forkB} (deve ser só broadcast/user):")
    for k, v in forkb_last_sender.most_common():
        print(f"     {k:18s} {v}")
    print(f"Overdue sob FIX REAL (impl shipada, atraso só se cliente falou por último): {overdue_forkA}")
    print(f"\nQuebra por sent_by da ÚLTIMA mensagem real das conversas marcadas:")
    for k, v in true_last_sender_counter.most_common():
        flag = "  <-- cliente (ok)" if k == "user" else "  <-- nosso lado (FALSO)"
        print(f"   {k:18s} {v}{flag}")

    print(f"\n========== EXEMPLOS DE FALSOS ATRASOS REMOVIDOS (últimas 4 msgs) ==========")
    for ex in examples:
        print(f"\nconv={ex['conv']} vendedor={ex['vendedor']!r} elapsed={ex['elapsed']}min "
              f"true_last={ex['true_last_sender']!r} lsra={ex['last_seller_response_at']}")
        for s, t in ex["tail"]:
            print(f"     {s:14s} {t}")

    print(f"\n========== ATRASOS QUE PERMANECEM SOB O FIX (Fork B) — devem ser genuínos ==========")
    for ex in forkb_examples:
        print(f"\nconv={ex['conv']} elapsed={ex['elapsed']}min  (últimas 5 msgs)")
        for s, t in ex["tail"]:
            print(f"     {s:14s} {t}")


if __name__ == "__main__":
    main()
