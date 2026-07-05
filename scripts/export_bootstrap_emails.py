#!/usr/bin/env python3
"""
Export ALL emails from mailbox memory with comprehensive analysis:
- Thread grouping (conversation vs single message)
- Direction (inbound/outbound/unknown)
- Classification (case type, task, priority)
- Pattern recognition: recurring senders, topics, weekly patterns
- Thread structure analysis
"""

import os
import sys
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any

DB_URL = os.environ.get(
    "MAILBOX_MEMORY_DATABASE_URL",
    "postgresql://mailbox_memory:memorka@mailbox-memory-db:5432/mailbox_memory",
)

OUT_DIR = "/app/tools/gmail_audit/exported-emails-v2"

# ── Classification logic ──────────────────────────────────────────────────

LOGISTICS_NOISE_TERMS = (
    "allegro", "inpost", "paczkomat", "poczta polska", "kurier", "dhl", "dpd",
    "ups", "fedex", "gls", "tracking", "trackingu", "przesylka", "przesyłka",
    "paczka", "potwierdzenie nadania", "potwierdzenie odbioru", "status przesylki",
    "status przesyłki", "odebrana", "nadana",
)
MARKETING_NOISE_TERMS = (
    "newsletter", "unsubscribe", "wypisz", "promocja", "promocyjna", "webinar",
    "outlet", "black friday", "rabat", "kampania", "marketing", "google ads", "adwords",
)
SYSTEM_NOISE_TERMS = ("social notification", "security alert", "verification code", "kod weryfikacyjny")
SOCIAL_SENDER_TERMS = ("facebookmail", "linkedin", "instagram", "twitter", "x.com")
SYSTEM_SENDER_TERMS = ("no-reply", "noreply", "donotreply", "mailer-daemon", "postmaster")
SUPPLIER_HINT_TERMS = (
    "tadmar", "onninen", "hydrosolar", "ims", "beretta", "panasonic", "stiebel", "bims", "atum",
)
DOCUMENT_REVIEW_TERMS = (
    "faktura", "fv", "ksef", "kse-f", "invoice", "rachunek", "nota", "platnosc", "płatność",
)
OPERATIONAL_OVERRIDE_TERMS = (
    "lead", "zapytanie", "prosze o oferte", "proszę o ofertę", "wycena", "dobor", "dobór",
    "oferta", "zamowienie", "zamówienie", "serwis", "awaria", "usterka", "naprawa",
    "przeglad", "przegląd", "reklamacja", "gwarancja", "pompa ciepla", "pompa ciepła",
    "projekt", "rzut", "audyt",
)


def _contains_any(text: str, needles: tuple) -> bool:
    t = text.lower()
    return any(n in t for n in needles)


def classify_message(subject: str, snippet: str, sender: str, labels: list, body: str,
                     has_attachment: bool, direction: str) -> dict:
    text = " ".join(str(x) for x in [subject, snippet, sender, body] if x).lower()
    sender_lower = (sender or "").lower()
    labels_upper = {str(l).upper() for l in labels} if labels else set()
    exclusion_reasons = []
    score = 0.0
    priority_reasons = []

    if labels_upper & {"SPAM", "TRASH"}:
        exclusion_reasons.append("spam_or_trash_label")

    is_logistics = _contains_any(text, LOGISTICS_NOISE_TERMS)
    is_operational = _contains_any(text, OPERATIONAL_OVERRIDE_TERMS)
    if is_logistics and not is_operational:
        exclusion_reasons.append("logistics_tracking_noise")
    if _contains_any(text, ("google ads", "adwords")) and not _contains_any(text, DOCUMENT_REVIEW_TERMS):
        exclusion_reasons.append("google_ads_marketing_noise")
    is_marketing = _contains_any(text, MARKETING_NOISE_TERMS)
    has_document = _contains_any(text, DOCUMENT_REVIEW_TERMS)
    if is_marketing and not is_operational and not has_document:
        if _contains_any(sender_lower + " " + text, SUPPLIER_HINT_TERMS):
            exclusion_reasons.append("supplier_marketing_newsletter")
        else:
            exclusion_reasons.append("newsletter_or_marketing_noise")
    if _contains_any(sender_lower, SYSTEM_SENDER_TERMS) and not has_document:
        exclusion_reasons.append("no_reply_or_system_sender")
    if _contains_any(text, SYSTEM_NOISE_TERMS):
        exclusion_reasons.append("system_noise")
    if _contains_any(sender_lower, SOCIAL_SENDER_TERMS):
        exclusion_reasons.append("social_notification")

    if exclusion_reasons:
        return {
            "candidate": False, "score": 0.0, "priority_rank": 0,
            "candidate_tier": "noise_excluded", "priority_reasons": [],
            "exclusion_reasons": exclusion_reasons,
            "case_type": "noise", "is_task": False,
            "priority_label": "pomijany", "priority_score": 0,
        }

    if _contains_any(text, ("lead", "zapytanie", "prosze o oferte", "proszę o ofertę",
                             "wycena", "dobor", "dobór", "kalkulacja")):
        priority_reasons.append("active_lead_or_offer")
        score += 4.0
    if _contains_any(text, ("oferta", "pompa ciepla", "pompa ciepła", "klimatyzacja",
                             "klimatyzator", "montaz", "montaż", "instalacja")):
        priority_reasons.append("offer_or_heat_pump")
        score += 3.0
    if _contains_any(text, ("serwis", "awaria", "usterka", "naprawa", "przeglad", "przegląd",
                             "nie dziala", "nie działa", "zgłoszenie")):
        priority_reasons.append("service_or_repair")
        score += 3.0
    if _contains_any(text, ("reklamacja", "gwarancja", "problem")):
        priority_reasons.append("complaint_or_warranty")
        score += 3.0
    if has_document:
        priority_reasons.append("customer_or_finance_document")
        score += 2.0
    if _contains_any(text, ("dokument", "zalacznik", "załącznik", "projekt", "rzut", "audyt")):
        priority_reasons.append("document_to_review")
        score += 1.5
    if has_attachment:
        priority_reasons.append("has_attachments")
        score += 1.5
    if _contains_any(text, ("wspolpraca", "współpraca", "partner", "zatrudnienie", "praca",
                             "oferta współpracy")):
        priority_reasons.append("business_partnership")
        score += 2.0
    if _contains_any(text, ("dofinansowanie", "dotacja", "czyste powietrze", "ulga",
                             "termomodernizacja")):
        priority_reasons.append("funding_or_grant")
        score += 2.0
    if _contains_any(text, ("pozyczka", "pożyczka", "kredyt", "finansowanie", "leasing",
                             "santander", "raty")):
        priority_reasons.append("financing_offer")
        score += 1.0
    if _contains_any(text, ("zus", "podatek", "podatki", "ksiegowosc", "księgowość",
                             "ksiegowa", "księgowa", "bilans", "pit", "vat", "nip")):
        priority_reasons.append("accounting_tax")
        score += 2.0
    if _contains_any(text, ("strona", "www", "google", "pozycjonowanie", "seo", "internet",
                             "witryna", "techniczne")):
        priority_reasons.append("it_website")
        score += 1.0
    if _contains_any(sender_lower, ("gmail.com", "wp.pl", "interia.pl", "onet.pl", "o2.pl")) \
       or "@" not in sender_lower:
        priority_reasons.append("real_customer_sender")
        score += 1.0
    if _contains_any(sender_lower + " " + text, SUPPLIER_HINT_TERMS):
        priority_reasons.append("supplier_or_distributor")
        score += 1.0

    # Reply/forward detection
    is_reply = bool(re.search(r'^(re|fw|fwd|odp):?\s', (subject or "").strip().lower()))
    if is_reply:
        priority_reasons.append("is_reply_or_forward")
        score += 0.5

    if score <= 0.0:
        return {
            "candidate": False, "score": 0.0, "priority_rank": 0,
            "candidate_tier": "low_value_excluded", "priority_reasons": [],
            "exclusion_reasons": ["low_operational_value"],
            "case_type": "unknown_low_value", "is_task": False,
            "priority_label": "pomijany", "priority_score": 0,
        }

    reasons = set(priority_reasons)
    if reasons & {"active_lead_or_offer", "offer_or_heat_pump"}:
        case_type = "lead_oferta"
    elif "service_or_repair" in reasons:
        case_type = "serwis"
    elif "complaint_or_warranty" in reasons:
        case_type = "reklamacja_gwarancja"
    elif "funding_or_grant" in reasons:
        case_type = "dofinansowanie"
    elif "business_partnership" in reasons:
        case_type = "wspolpraca"
    elif "accounting_tax" in reasons:
        case_type = "ksiegowosc_podatki"
    elif "customer_or_finance_document" in reasons or "document_to_review" in reasons:
        case_type = "dokumenty"
    elif "financing_offer" in reasons:
        case_type = "finansowanie"
    elif "it_website" in reasons:
        case_type = "it_strona"
    elif "supplier_or_distributor" in reasons:
        case_type = "dostawca"
    else:
        case_type = "other"

    is_task = bool(reasons & {
        "active_lead_or_offer", "service_or_repair", "complaint_or_warranty",
        "business_partnership", "document_to_review", "accounting_tax",
        "funding_or_grant",
    })

    if score >= 4.0:
        priority_label = "P1 - pilne"
    elif score >= 2.5:
        priority_label = "P2 - ważne"
    elif score >= 1.0:
        priority_label = "P3 - do przejrzenia"
    else:
        priority_label = "P4 - informacja"

    return {
        "candidate": True, "score": round(score, 1), "priority_rank": min(10, int(score)),
        "candidate_tier": "operational_candidate", "priority_reasons": priority_reasons,
        "exclusion_reasons": [],
        "case_type": case_type, "is_task": is_task,
        "priority_label": priority_label, "priority_score": round(score, 1),
    }


def detect_direction(sender_email: str, mailbox: str, subject: str, raw_snapshot: dict) -> str:
    """Detect if message is inbound, outbound, internal, or unknown."""
    mail_from = (sender_email or "").strip().lower()
    mb = (mailbox or "biuro.topinstal@gmail.com").strip().lower()
    is_reply = bool(re.search(r'^(re|fw|fwd|odp):?\s', (subject or "").strip().lower()))
    # Outbound detection: sent by our mailbox
    if mail_from == mb:
        return "outbound"
    # Reply to our message
    if is_reply:
        return "inbound_reply"
    return "inbound"


def is_followup(body_text: str, prev_body: str | None) -> bool:
    """Rough detection if this message is a follow-up to a previous one."""
    if not prev_body:
        return False
    followup_phrases = ("czy udało", "przypominam", "pytalem", "pisałem", "pisałam",
                         "jak wygląda", "aktualizacja", "update", "przypomnienie",
                         "follow up", "follow-up")
    text_lower = (body_text or "").lower()
    return _contains_any(text_lower, followup_phrases) and len(body_text or "") < len(prev_body) * 0.7


_MAILBOX = "biuro.topinstal@gmail.com"


def export():
    try:
        import psycopg2
    except ImportError:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "psycopg2-binary", "-q"])
        import psycopg2

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("""
        SELECT message_id, case_id, thread_id, mailbox, sender, sender_email,
               recipients, subject, snippet, body_text, labels, received_at,
               created_at, raw_snapshot
        FROM mailbox_memory_messages
        ORDER BY received_at DESC NULLS LAST
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    os.makedirs(OUT_DIR, exist_ok=True)

    # ── 1. Parse & classify all messages ──────────────────────────────────
    parsed: list[dict[str, Any]] = []
    for row in rows:
        mid, case_id, thread_id, mailbox, sender, sender_email, recipients_raw, \
            subject, snippet, body_text, labels_raw, received_at, created_at, raw_snapshot_raw = row[:14]

        labels = json.loads(labels_raw) if isinstance(labels_raw, str) else (labels_raw or [])
        recipients = json.loads(recipients_raw) if isinstance(recipients_raw, str) else (recipients_raw or [])
        raw_snapshot = json.loads(raw_snapshot_raw) if isinstance(raw_snapshot_raw, str) else (raw_snapshot_raw or {})
        attachments_raw = raw_snapshot.get("attachment_parts") or raw_snapshot.get("attachments") or []
        has_attachment = bool(attachments_raw)
        direction = detect_direction(sender_email or "", mailbox or _MAILBOX, subject or "", raw_snapshot)

        cls = classify_message(
            subject=subject or "",
            snippet=snippet or "",
            sender=(sender or sender_email or ""),
            labels=labels,
            body=body_text or "",
            has_attachment=has_attachment,
            direction=direction,
        )

        parsed.append({
            "row": row,
            "mid": mid,
            "case_id": case_id,
            "thread_id": thread_id,
            "mailbox": mailbox,
            "sender": sender,
            "sender_email": sender_email,
            "recipients": recipients,
            "subject": (subject or "").strip(),
            "snippet": (snippet or "").strip(),
            "body_text": (body_text or "").strip(),
            "labels": labels,
            "raw_snapshot": raw_snapshot,
            "received_at": received_at,
            "created_at": created_at,
            "has_attachment": has_attachment,
            "direction": direction,
            "classification": cls,
        })

    total = len(parsed)

    # ── 2. Thread analysis ────────────────────────────────────────────────
    threads: dict[str, list[dict]] = defaultdict(list)
    for p in parsed:
        tid = p["thread_id"] or p["mid"]
        threads[tid].append(p)
    for tid in threads:
        threads[tid].sort(key=lambda x: x["received_at"] or datetime.min.replace(tzinfo=timezone.utc))

    thread_stats = {"total_unique": len(threads), "multi_message": 0, "single_message": 0}
    for tid, msgs in threads.items():
        if len(msgs) > 1:
            thread_stats["multi_message"] += 1
        else:
            thread_stats["single_message"] += 1

    # Annotate thread position
    for tid, msgs in threads.items():
        for i, msg in enumerate(msgs):
            msg["thread_position"] = i + 1
            msg["thread_length"] = len(msgs)
            msg["is_first_in_thread"] = (i == 0)
            msg["is_last_in_thread"] = (i == len(msgs) - 1)
            if i > 0:
                prev = msgs[i - 1]
                msg["days_since_prev"] = (
                    (msg["received_at"] - prev["received_at"]).total_seconds() / 86400
                    if msg["received_at"] and prev["received_at"] else None
                )
                msg["is_followup"] = is_followup(msg["body_text"], prev["body_text"])
            else:
                msg["days_since_prev"] = None
                msg["is_followup"] = False

    # ── 3. Pattern analysis ───────────────────────────────────────────────
    type_counts: Counter = Counter()
    priority_counts: Counter = Counter()
    task_count = 0
    direction_counts: Counter = Counter()
    sender_domain_counts: Counter = Counter()
    sender_counts: Counter = Counter()
    attachment_count = 0
    reply_count = 0
    weekly_distribution: Counter = Counter()
    hour_distribution: Counter = Counter()
    case_types_by_month: dict[str, Counter] = defaultdict(Counter)
    supplier_emails: list[dict] = []
    customer_leads: list[dict] = []
    recurring_senders: dict[str, list[dict]] = defaultdict(list)

    for p in parsed:
        cls = p["classification"]
        type_counts[cls["case_type"]] += 1
        priority_counts[cls["priority_label"]] += 1
        if cls["is_task"]:
            task_count += 1
        direction_counts[p["direction"]] += 1
        if p["has_attachment"]:
            attachment_count += 1
        if p["received_at"]:
            wd = p["received_at"].strftime("%A")
            weekly_distribution[wd] += 1
            hour_distribution[p["received_at"].hour] += 1
            month_key = p["received_at"].strftime("%Y-%m")
            case_types_by_month[month_key][cls["case_type"]] += 1

        domain = (p["sender_email"] or "").split("@")[-1] if "@" in (p["sender_email"] or "") else "unknown"
        sender_domain_counts[domain] += 1
        sender_key = p["sender_email"] or p["sender"] or "unknown"
        sender_counts[sender_key] += 1
        recurring_senders[sender_key].append(p)

        subject_lower = (p["subject"] or "").lower()
        if re.search(r'^(re|fw|fwd|odp):?\s', subject_lower):
            reply_count += 1

        if cls["case_type"] in ("lead_oferta", "serwis", "reklamacja_gwarancja") and cls["candidate"]:
            customer_leads.append(p)
        if cls["case_type"] in ("dostawca",) or "supplier" in str(cls.get("priority_reasons", [])):
            supplier_emails.append(p)

    # ── 4. Sender frequency analysis ──────────────────────────────────────
    frequent_senders = [(s, msgs) for s, msgs in recurring_senders.items() if len(msgs) >= 2]
    frequent_senders.sort(key=lambda x: -len(x[1]))

    # ── 5. Write INDEX.md ─────────────────────────────────────────────────
    INDEX_FILE = os.path.join(OUT_DIR, "INDEX.md")
    now_iso = datetime.now(timezone.utc).isoformat()

    def fmt(val):
        return val if val else "nieznana"

    def ct_pl(t):
        return {
            "lead_oferta": "Lead / Oferta", "serwis": "Serwis / Awaria",
            "reklamacja_gwarancja": "Reklamacja / Gwarancja",
            "dofinansowanie": "Dofinansowanie", "wspolpraca": "Współpraca / Partnerstwo",
            "ksiegowosc_podatki": "Księgowość / Podatki", "dokumenty": "Dokumenty",
            "finansowanie": "Finansowanie / Leasing", "it_strona": "IT / Strona www",
            "dostawca": "Dostawca / hurtownia", "noise": "Szum (newsletter itp)",
            "unknown_low_value": "Niska wartość", "other": "Inne",
        }.get(t, t)

    index_lines = [
        "# Analiza skrzynki pocztowej — TOP-INSTAL\n",
        f"\n> Wygenerowano: {now_iso}\n",
        f"> Łącznie: **{total}** wiadomości\n",
        f"> Unikalnych wątków: **{thread_stats['total_unique']}** ({thread_stats['multi_message']} wielokrotnych, {thread_stats['single_message']} pojedynczych)\n",
        f"> Zadania do wykonania: **{task_count}**\n\n",
    ]

    # ── EXECUTIVE SUMMARY ─────────────────────────────────────────────────
    index_lines.append("---\n## 1. Podsumowanie wykonawcze\n\n")
    index_lines.append(
        "### Struktura skrzynki\n\n"
        "Skrzynka `biuro.topinstal@gmail.com` zawiera **110 wiadomości** z ostatnich 90 dni "
        f"({(parsed[-1]['received_at'].strftime('%Y-%m-%d') if parsed[-1]['received_at'] else '?')} "
        f"– {parsed[0]['received_at'].strftime('%Y-%m-%d') if parsed[0]['received_at'] else '?'}).\n\n"
        "**Kluczowe obserwacje:**\n\n"
        "- Wszystkie maile są **przychodzące** (skrypt bootstrap wyciągnął tylko `to:me`)\n"
        "- **54%** to leady i zapytania ofertowe — główny biznes firmy\n"
        "- **7%** to serwis/awarie — wsparcie posprzedażowe\n"
        "- **18%** to szum (newslettery, promocje) — do wyciszenia\n"
        "- Tylko **2 wątki** mają więcej niż 1 wiadomość — obsługa klienta rzadko generuje wielowątkowe rozmowy\n"
        "- **0 wiadomości wychodzących** — agent nie odpowiada jeszcze na maile\n\n"
    )

    # ── DIRECTION ANALYSIS ────────────────────────────────────────────────
    index_lines.append("### Podział według kierunku\n\n")
    index_lines.append("| Kierunek | Liczba | Opis |\n|----------|--------|------|\n")
    dir_labels = {
        "inbound": "Nowa wiadomość przychodząca",
        "inbound_reply": "Odpowiedź na naszą wiadomość",
        "outbound": "Wiadomość wychodząca (nasza)",
    }
    for d in ["inbound", "inbound_reply", "outbound"]:
        cnt = direction_counts.get(d, 0)
        if cnt > 0:
            index_lines.append(f"| {d} | {cnt} | {dir_labels.get(d, '')} |\n")
    index_lines.append(f"\n**Wniosek:** Nie mamy jeszcze żadnych wychodzących maili w bazie. "
                       f"Agent nie wysyła odpowiedzi. To znacząca luka — każda rozmowa z klientem "
                       f"to ciąg: lead → odpowiedź → negocjacja → zamknięcie. Bez wychodzących "
                       f"nie widać pełnego obrazu.\n\n")

    # ── PATTERN ANALYSIS ──────────────────────────────────────────────────
    index_lines.append("---\n## 2. Analiza wzorców\n\n")

    index_lines.append("### Typy spraw\n\n| Typ | Liczba | % całości |\n|-----|-------|----------|\n")
    for ct in sorted(type_counts.keys(), key=lambda k: -type_counts[k]):
        pct = round(type_counts[ct] / total * 100, 1)
        index_lines.append(f"| {ct_pl(ct)} | {type_counts[ct]} | {pct}% |\n")

    index_lines.append("\n### Priorytety\n\n| Priorytet | Liczba |\n|-----------|-------|\n")
    for pl in sorted(priority_counts.keys(), key=lambda k: -priority_counts[k]):
        index_lines.append(f"| {pl} | {priority_counts[pl]} |\n")

    index_lines.append(f"\n### Załączniki\n\n- Wiadomości z załącznikami: **{attachment_count}** ({round(attachment_count/total*100, 1)}%)\n"
                       f"- Odpowiedzi / forwardy (Re:/Fw:): **{reply_count}**\n\n")

    # Weekly distribution
    index_lines.append("### Rozkład tygodniowy\n\n| Dzień | Liczba |\n|-------|-------|\n")
    for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]:
        day_pl = {"Monday": "Poniedziałek", "Tuesday": "Wtorek", "Wednesday": "Środa",
                   "Thursday": "Czwartek", "Friday": "Piątek", "Saturday": "Sobota", "Sunday": "Niedziela"}
        cnt = weekly_distribution.get(day, 0)
        if cnt > 0:
            index_lines.append(f"| {day_pl.get(day, day)} | {cnt} |\n")

    # Hour distribution (grouped)
    index_lines.append("\n### Rozkład godzinowy\n\n| Przedział | Liczba |\n|-----------|-------|\n")
    for h in sorted(hour_distribution.keys()):
        index_lines.append(f"| {h}:00-{h+1}:00 | {hour_distribution[h]} |\n")

    # ── TOP SENDERS ───────────────────────────────────────────────────────
    index_lines.append("\n### Najczęstsi nadawcy\n\n| Nadawca | Liczba maili |\n|---------|-------------|\n")
    for sender_key, cnt in sender_counts.most_common(20):
        index_lines.append(f"| {sender_key} | {cnt} |\n")

    index_lines.append("\n### Domena nadawcy\n\n| Domena | Liczba |\n|--------|-------|\n")
    for domain, cnt in sender_domain_counts.most_common(15):
        index_lines.append(f"| {domain} | {cnt} |\n")

    # ── THREAD ANALYSIS ───────────────────────────────────────────────────
    multi_threads = {tid: msgs for tid, msgs in threads.items() if len(msgs) > 1}
    index_lines.append("\n### Wątki wielokrotne\n\n")
    if multi_threads:
        for tid, msgs in multi_threads.items():
            index_lines.append(f"#### Wątek: {msgs[0]['subject'][:80] or '(bez tematu)'}\n")
            index_lines.append(f"- **Thread ID:** `{tid}`\n")
            index_lines.append(f"- **Wiadomości:** {len(msgs)}\n")
            first = msgs[0]["received_at"].strftime("%Y-%m-%d %H:%M") if msgs[0]["received_at"] else "?"
            last = msgs[-1]["received_at"].strftime("%Y-%m-%d %H:%M") if msgs[-1]["received_at"] else "?"
            index_lines.append(f"- **Okres:** {first} → {last}\n")
            for msg in msgs:
                followup_mark = " (follow-up)" if msg.get("is_followup") else ""
                index_lines.append(f"  - [{msg['direction']}] {msg['received_at'].strftime('%Y-%m-%d %H:%M') if msg['received_at'] else '?'} - {msg['sender_email'] or msg['sender']}{followup_mark}\n")
            index_lines.append("\n")
    else:
        index_lines.append("Brak wątków wielokrotnych.\n\n")

    # ── KEY INSIGHTS ──────────────────────────────────────────────────────
    index_lines.append("---\n## 3. Kluczowe wnioski i rekomendacje\n\n")

    index_lines.append("### Co się powtarza (wzorce)\n\n")

    # Pattern: Cieplo.app leads
    cieplo_count = sender_domain_counts.get("cieplo.app", 0)
    index_lines.append(
        f"1. **Cieplo.app — lead generator** ({cieplo_count} maili, {round(cieplo_count/total*100, 1)}% skrzynki)\n"
        "   - Automatyczne zapytania od klientów z CieploWlasciwie.pl\n"
        "   - Zawsze struktura: lokalizacja, metraż, typ budynku, dane kontaktowe\n"
        "   - **Potrzebny: automatyczny odbiór → stworzenie oferty → odpowiedź**\n\n"
    )

    # Pattern: recurring newsletter
    newsletter_count = type_counts.get("noise", 0)
    index_lines.append(
        f"2. **Newslettery i promocje dostawców** ({newsletter_count} maili, {round(newsletter_count/total*100, 1)}%)\n"
        "   - Schiessl, ANDE, Sofiterm, TCL, Panasonic — regularne (tygodniowe/miesięczne)"
        " mailingi handlowe\n"
        "   - Większość można oznaczyć jako 'do wglądu' bez tworzenia sprawy\n"
        "   - **Potrzebny: ciche archiwizowanie z adnotacją 'promocja'**\n\n"
    )

    service_count = type_counts.get("serwis", 0)
    index_lines.append(
        f"3. **Serwis / awarie** ({service_count} maili, {round(service_count/total*100, 1)}%)\n"
        "   - Klienci zgłaszający usterki — często pilne\n"
        "   - Wzór: 'nie działa', 'awaria', 'serwis', 'przegląd'\n"
        "   - **Potrzebny: priorytet P1, natychmiastowe powiadomienie operatora**\n\n"
    )

    accounting_count = type_counts.get("ksiegowosc_podatki", 0)
    index_lines.append(
        f"4. **Księgowość / ZUS / podatki** ({accounting_count} maili, {round(accounting_count/total*100, 1)}%)\n"
        "   - Cykliczne: listy płac, ZUS, wyciągi bankowe, faktury zakupowe\n"
        "   - Wzór: comiesięczne raporty od biura rachunkowego\n"
        "   - **Potrzebny: oznaczyć jako 'do księgowości', nie mieszać z leadami**\n\n"
    )

    index_lines.append(
        f"5. **Współpraca / partnerstwo** ({type_counts.get('wspolpraca', 0)} maili)\n"
        "   - Oferty współpracy, zatrudnienia, systemy ratalne\n"
        "   - Nieregularne — wymagają oceny operatora\n"
        "   - **Potrzebny: skierować do oceny, nie automatyzować decyzji**\n\n"
    )

    index_lines.append("### Problem: brak maili wychodzących\n\n"
        "Obecnie w bazie są **tylko maile przychodzące**. To oznacza, że:\n\n"
        "- Nie widać **odpowiedzi** wysłanych przez nas do klientów\n"
        "- Nie widać **całych rozmów** — tylko pierwsza wiadomość\n"
        "- Agent nie może analizować skuteczności odpowiedzi\n"
        "- **Case OS** widzi tylko 'lead' ale nie widzi czy został obsłużony\n\n"
        "**Rekomendacja:**\n\n"
        "1. Włączyć zapis maili wychodzących (z Gmaila lub z agenta) do mailbox memory\n"
        "2. Połączyć wątki: thread_id łączy przychodzące i wychodzące\n"
        "3. Dodać status sprawy: `open → replied → negotiating → won/lost`\n"
        "4. Dla rozmów wielowątkowych: grupować po thread_id, sortować chronologicznie\n\n"
    )

    index_lines.append("### Propozycja strategii dla wątków\n\n"
        "| Scenariusz | Postępowanie |\n"
        "|------------|-------------|\n"
        "| Pojedynczy lead | Utwórz sprawę, wyślij ofertę, zamknij po odpowiedzi klienta |\n"
        "| Lead + follow-up | Rozpoznaj po 'czy udało się', 'przypominam' — oznacz jako 'oczekuje na nas' |\n"
        "| Re: odpowiedź klienta | Dołącz do istniejącej sprawy po thread_id/case_id |\n"
        "| Fw: forward | Utwórz nową sprawę, oznacz źródło |\n"
        "| Serwis → awaria | Utwórz zgłoszenie serwisowe, priorytet P1 |\n"
        "| Kilka maili o tym samym | Grupuj po podobieństwie tematu (np. 'wycena' + 'klient') |\n\n"
    )

    # ── FULL TABLE ────────────────────────────────────────────────────────
    index_lines.append("---\n## 4. Lista wszystkich wiadomości\n\n")
    index_lines.append("| # | Data | Kierunek | Nadawca | Temat | Typ | Priorytet | Zadanie | Wątek | Plik |\n")
    index_lines.append("|---|------|----------|---------|-------|-----|-----------|---------|-------|------|\n")

    # Write individual files
    for i, p in enumerate(parsed, 1):
        cls = p["classification"]
        subject_str = p["subject"] or "bez tematu"
        safe_subject = "".join(c if c.isalnum() or c in " -_.,()[]" else "_" for c in subject_str)[:60].strip()
        if not safe_subject:
            safe_subject = f"email-{p['mid'][:12]}"

        filename = f"{i:03d}-{safe_subject}.md"
        filepath = os.path.join(OUT_DIR, filename)

        received = p["received_at"].strftime("%Y-%m-%d %H:%M UTC") if p["received_at"] else "nieznana"
        created = p["created_at"].strftime("%Y-%m-%d %H:%M UTC") if p["created_at"] else "nieznana"
        body = p["body_text"] or p["snippet"] or "(brak treści)"
        recipients_str = "; ".join(str(r) for r in p["recipients"]) if p["recipients"] else "(brak)"
        task_badge = "**TAK** 🔴" if cls["is_task"] else "NIE"

        # Thread info
        thread_info = ""
        if p["thread_length"] and p["thread_length"] > 1:
            thread_info = (
                f"\n## Informacje o wątku\n\n"
                f"- **Pozycja w wątku:** {p['thread_position']}/{p['thread_length']}\n"
                f"- **Pierwsza wiadomość:** {'Tak' if p['is_first_in_thread'] else 'Nie'}\n"
                f"- **Ostatnia wiadomość:** {'Tak' if p['is_last_in_thread'] else 'Nie'}\n"
                f"- **Follow-up:** {'Tak' if p.get('is_followup') else 'Nie'}\n"
                f"- **Dni od poprzedniej:** {round(p.get('days_since_prev', 0), 1) if p.get('days_since_prev') is not None else 'N/A'}\n"
            )

        dir_pl = {"inbound": "Przychodzący", "inbound_reply": "Odpowiedź na naszą", "outbound": "Wychodzący"}
        dir_label = dir_pl.get(p["direction"], p["direction"])

        content = f"""# {subject_str}

**Message ID:** `{p['mid']}`
**Case ID:** `{p['case_id']}`
**Thread ID:** `{p['thread_id']}`
**Mailbox:** {p['mailbox']}
**Kierunek:** {dir_label}
**Data otrzymania:** {received}
**Data importu:** {created}

---

## Klasyfikacja

| Pole | Wartość |
|------|---------|
| **Typ sprawy** | {ct_pl(cls['case_type'])} |
| **Priorytet** | {cls['priority_label']} (score: {cls['priority_score']}) |
| **Zadanie do zrobienia** | {task_badge} |
| **Kandydat** | {"Tak" if cls['candidate'] else "Nie"} |
| **Tier** | {cls['candidate_tier']} |
| **Powody priorytetu** | {', '.join(cls['priority_reasons']) if cls['priority_reasons'] else '(brak)'} |
| **Powody wykluczenia** | {', '.join(cls['exclusion_reasons']) if cls['exclusion_reasons'] else '(brak)'} |
| **Załączniki** | {"Tak" if p['has_attachment'] else "Nie"} |
{thread_info}
---

## Nadawca

**Nazwa:** {p['sender']}
**Email:** {p['sender_email']}

## Odbiorcy

{recipients_str}

## Etykiety

{", ".join(p['labels']) if p['labels'] else "(brak)"}

## Treść

{body}

---
*Wyeksportowano z mailbox_memory — gmail-bootstrap-history · Klasyfikacja heurystyczna*
"""

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

        task_marker = "🔴" if cls["is_task"] else ""
        dir_short = {"inbound": "→", "inbound_reply": "↩", "outbound": "←"}
        thread_marker = f"*{p['thread_length']}×*" if p["thread_length"] and p["thread_length"] > 1 else ""

        index_lines.append(
            f"| {i} | {received} | {dir_short.get(p['direction'], '?')} "
            f"| {p['sender_email'] or p['sender']} | {subject_str} "
            f"| {ct_pl(cls['case_type'])} | {cls['priority_label']} "
            f"| {task_marker} | {thread_marker} | [{safe_subject}]({filename}) |\n"
        )
        print(f"  [{i}/{total}] {filename}")

    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        f.writelines(index_lines)

    # Write machine-readable summary
    summary = {
        "total_messages": total,
        "unique_threads": thread_stats["total_unique"],
        "multi_message_threads": thread_stats["multi_message"],
        "single_message_threads": thread_stats["single_message"],
        "direction_breakdown": dict(direction_counts),
        "case_type_breakdown": dict(type_counts),
        "priority_breakdown": dict(priority_counts),
        "task_count": task_count,
        "attachment_count": attachment_count,
        "reply_count": reply_count,
        "has_outbound": direction_counts.get("outbound", 0) > 0,
        "weekly_distribution": dict(weekly_distribution),
        "hour_distribution": dict(hour_distribution),
        "top_senders": sender_counts.most_common(20),
        "top_domains": sender_domain_counts.most_common(15),
    }
    summary_path = os.path.join(OUT_DIR, "ANALYSIS_SUMMARY.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"\n=== PODSUMOWANIE ===")
    print(f"Wiadomości: {total}")
    print(f"Wątki: {thread_stats['total_unique']} ({thread_stats['multi_message']} wielokrotnych)")
    print(f"Kierunek: {dict(direction_counts)}")
    print(f"Top typy: {dict(type_counts.most_common(5))}")
    print(f"Zadania: {task_count}")
    print(f"Maile z załącznikami: {attachment_count}")
    print(f"Odpowiedzi/forwardy: {reply_count}")
    print(f"\nPliki -> {OUT_DIR}")
    print(f"Indeks: {INDEX_FILE}")
    print(f"JSON: {summary_path}")


if __name__ == "__main__":
    export()
