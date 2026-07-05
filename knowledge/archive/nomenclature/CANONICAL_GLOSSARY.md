# Słownik kanoniczny TOP-INSTAL (warstwy L1–L3)

**Wersja:** 2026-05-23
**Status:** Governance (faza 2) — uzupełnia Discovery As-Is
**Wpisy:** 99 pojęć kanonicznych (L2) z polskim L1

## Jak czytać tabelę

| Kolumna            | Znaczenie                                                                 |
| ------------------ | ------------------------------------------------------------------------- |
| **ID (L2)**        | Kanoniczny identyfikator — używaj w RFC, registry, nowym API              |
| **PL (L1)**        | Termin dla operatora, UI, szkoleń — **jeden** na wiersz                   |
| **Warstwa**        | `L1` tylko PL · `L2` kontrakt · `L3` = wyłącznie implementacja istniejąca |
| **Repo**           | Gdzie żyje implementacja lub gdzie **nie wolno** duplikować               |
| **L3 (przykłady)** | Tokeny As-Is — **nie rename** jeśli 🔒                                    |
| **Uwagi**          | Granice, P0/P1, kolizje                                                   |

🔒 = kotwica zamrożona (`immutable` w `ALIAS_REGISTRY.yaml`)

---

## A. Warstwa OS (greenfield — L2, brak w kodzie dziś)

| ID (L2)                  | PL (L1)                              | Warstwa | Repo            | L3 (przykłady)                          | Uwagi                                                    |
| ------------------------ | ------------------------------------ | ------- | --------------- | --------------------------------------- | -------------------------------------------------------- |
| `os.identity`            | Tożsamość klienta                    | L2      | registry (nowy) | — brak `identity_id`                    | Osoba/firma; wiele kanałów kontaktu                      |
| `os.identity_id`         | Identyfikator klienta (systemowy)    | L2      | registry        | —                                       | UUID; nie zastępuje email w tabelach źródłowych          |
| `os.engagement`          | Zaangażowanie biznesowe              | L2      | registry        | —                                       | Relacja „obsługujemy tego klienta w tym wątku”           |
| `os.engagement_id`       | Identyfikator zaangażowania          | L2      | registry        | —                                       | Łączy 0..1 sprawę + 0..1 zlecenie Cieplo + linki         |
| `os.correlation_link`    | Powiązanie między systemami          | L2      | registry        | —                                       | Wiersz w `correlation_links`; nie merge DB               |
| `os.canonical_trace_id`  | Identyfikator przebiegu (kanoniczny) | L2      | registry        | mapuje 🔒 `traceId` / `trace_id`        | Jeden przebieg oferty / pipeline                         |
| `os.engagement_snapshot` | Widok złożony zaangażowania          | L2      | read API (nowy) | składa 🔒 CaseContextPack + workflow    | Daszek „ten sam klient”                                  |
| `os.event_envelope`      | Koperta zdarzenia (spine)            | L2      | P1 spine        | —                                       | Append-only cross-system                                 |
| `os.event_spine`         | Oś zdarzeń                           | L2      | P1              | lokalne: SignalJournal, workflow_events | Zastępuje semantykę „wiele journali”, nie tabele od razu |
| `os.decision_record`     | Rekord decyzji                       | L2      | P1 pipeline     | 🔒 `action_proposal`, policy\_\*        | Jedyna droga do wykonania akcji (docelowo)               |

---

## B. Klient i kontakt

| ID (L2)                   | PL (L1)                              | Warstwa | Repo                  | L3 (przykłady)                                    | Uwagi                                     |
| ------------------------- | ------------------------------------ | ------- | --------------------- | ------------------------------------------------- | ----------------------------------------- |
| `identity.contact_email`  | E-mail klienta                       | L2      | wszystkie             | 🔒 `customer_email`, `client_email`, `lead.email` | P0: ten sam email → ten sam `identity_id` |
| `identity.contact_name`   | Nazwa klienta                        | L2      | gmail-agent, kalk-top | 🔒 `customer_name`, `lead.name`                   |                                           |
| `identity.contact_phone`  | Telefon klienta                      | L2      | (przyszłe)            | —                                                 | Brak wspólnego pola dziś                  |
| `identity.channel.email`  | Kanał: e-mail                        | L2      | —                     | —                                                 | Typ kanału w registry                     |
| `party.operator`          | Operator (pracownik)                 | L1/L2   | Daszek, RAG auth      | —                                                 | Nie mylić z `identity` klienta            |
| `party.internal_reviewer` | Recenzent wewnętrzny (oferta Cieplo) | L1      | orchestrator          | env `INTERNAL_REVIEW_TO`                          | HITL przed SMTP do klienta                |

---

## C. Sprawa mailowa (gmail-agent / Node B)

| ID (L2)                   | PL (L1)                     | Warstwa | Repo                | L3 (przykłady)                      | Uwagi                        |
| ------------------------- | --------------------------- | ------- | ------------------- | ----------------------------------- | ---------------------------- |
| `case.mail_case`          | Sprawa mailowa              | L1/L2   | gmail-agent         | —                                   | SoT: Postgres mailbox_memory |
| `case.mail_case_id`       | Identyfikator sprawy        | L2      | gmail-agent         | 🔒 `case_id`                        | PK; API `/cases/{case_id}/`  |
| `case.case_key`           | Klucz sprawy (UI)           | L2      | gmail-agent, Daszek | 🔒 `case_key`                       | Etykieta; nie PK             |
| `case.case_family`        | Rodzina sprawy              | L2      | gmail-agent         | 🔒 `case_family`                    | Wpływa na derive case_id     |
| `case.thread`             | Wątek Gmail                 | L2      | gmail-agent         | 🔒 `thread_id`                      |                              |
| `case.message`            | Wiadomość Gmail             | L2      | gmail-agent         | 🔒 `message_id`                     | Kolizja #8 z workflows       |
| `case.context_pack`       | Pakiet kontekstu sprawy     | L2      | gmail-agent         | 🔒 `CaseContextPack`                | Read model po reconcile      |
| `case.context_pack_vnext` | Kontrakt vNext packu        | L2      | gmail-agent         | 🔒 `build_case_context_pack_vnext`  | Daszek / Skrzat / RAG caller |
| `case.snapshot_hot_state` | Gorący stan sprawy          | L2      | gmail-agent         | 🔒 `case_snapshot_hot_state`        | UI / policy                  |
| `case.reconcile`          | Uznanie prawdy po sygnale   | L2      | gmail-agent         | 🔒 `reconcile_signal`               | Po bridge drain              |
| `case.mailbox_memory`     | Pamięć skrzynki (magazyn)   | L2      | gmail-agent         | 🔒 tabele `mailbox_memory_*`        | Nie rename tabel             |
| `case.document_chunk`     | Fragment dokumentu sprawy   | L2      | gmail-agent         | 🔒 `mailbox_memory_document_chunks` | Nie Chroma RAG               |
| `case.external_ref`       | Odniesienie zewnętrzne (UI) | L2      | gmail-agent         | 🔒 `external_ref`                   | ≠ `external_key` Cieplo      |
| `case.intelligence`       | Warstwa rozumienia sprawy   | L2      | gmail-agent         | `case_intelligence.py`              | LLM nad packiem              |

---

## D. Zlecenie Cieplo (orchestrator)

| ID (L2)                        | PL (L1)                    | Warstwa | Repo         | L3 (przykłady)                          | Uwagi                        |
| ------------------------------ | -------------------------- | ------- | ------------ | --------------------------------------- | ---------------------------- |
| `cieplo.workflow`              | Zlecenie Cieplo (pipeline) | L1/L2   | orchestrator | 🔒 `workflows`, `WorkflowRow`           | **Nie** nazywać „sprawą”     |
| `cieplo.workflow_id`           | Identyfikator zlecenia     | L2      | orchestrator | 🔒 `workflows.id`; JSON 🔒 `lead_id`    | UI v2: „zlecenie Cieplo”     |
| `cieplo.workflow_state`        | Stan pipeline              | L2      | orchestrator | 🔒 `workflow_state`                     |                              |
| `cieplo.ingress_envelope`      | Koperta ingress Cieplo     | L2      | orchestrator | PayloadMapper output                    |                              |
| `cieplo.payload_type`          | Typ payload ingress        | L2      | orchestrator | 🔒 `cieplo_app_lead_v1`                 | Zamrożony typ                |
| `cieplo.ingress_status`        | Status ingress             | L2      | orchestrator | 🔒 `ingress_status`                     |                              |
| `cieplo.client_email`          | E-mail z maila Cieplo      | L2      | orchestrator | 🔒 `client_email`                       | → `identity.contact_email`   |
| `cieplo.external_key`          | Klucz Cieplo (email+URL)   | L2      | orchestrator | 🔒 `build_external_key`                 | Heurystyka P0 link           |
| `cieplo.parsed_result`         | Wynik parsowania HTML      | L2      | orchestrator | 🔒 `parsed_result`                      |                              |
| `cieplo.calc_request_snapshot` | Snapshot wejścia calc      | L2      | orchestrator | 🔒 `calc_request`                       | CalcRequestDTO JSON          |
| `cieplo.offer_snapshot`        | Snapshot oferty w pipeline | L2      | orchestrator | 🔒 `offer_json`                         | Kopia OfferDTO; nie edytować |
| `cieplo.pdf_artifact`          | Plik PDF oferty            | L2      | orchestrator | 🔒 `pdf_download_url`, `pdf_bytes_path` |                              |
| `cieplo.internal_review_email` | Mail wewnętrzny (review)   | L1      | orchestrator | SMTP internal                           | HITL                         |
| `cieplo.lead_offer_email`      | Mail oferty do klienta     | L1      | orchestrator | `build_lead_offer_email`                | Kolizja słowa „lead” #2      |

---

## E. Kalkulacja i oferta liczbowa (kalk-top)

| ID (L2)                   | PL (L1)                        | Warstwa | Repo                  | L3 (przykłady)                 | Uwagi                        |
| ------------------------- | ------------------------------ | ------- | --------------------- | ------------------------------ | ---------------------------- |
| `offer.numeric_offer`     | Oferta liczbowa                | L1/L2   | kalk-top              | 🔒 `OfferDTO`                  | Jedyny producent             |
| `offer.calc_request`      | Żądanie kalkulacji             | L2      | kalk-top              | 🔒 `CalcRequestDTO`            |                              |
| `offer.calc_request.lead` | Dane kontaktu w calc           | L2      | kalk-top              | 🔒 `lead` {name, email}        | **Nie** = zlecenie Cieplo    |
| `offer.schema_version`    | Wersja schematu                | L2      | kalk-top              | 🔒 `schemaVersion`             |                              |
| `offer.trace`             | Identyfikator przebiegu (DTO)  | L2      | kalk-top              | 🔒 `traceId`                   | Alias → `canonical_trace_id` |
| `offer.calculate_action`  | Akcja: przelicz ofertę         | L2      | kalk-top              | 🔒 `calculate-offer` REST      |                              |
| `offer.engineering`       | Inżynieria (dobór, OZC, bufor) | L2/HVAC | kalk-top              | 🔒 `OfferDTO.engineering`      | Nie rozlewać semantyki       |
| `offer.pricing`           | Wycena                         | L2/HVAC | kalk-top              | 🔒 `OfferDTO.pricing`          |                              |
| `hvac.ozc`                | Obliczenia OZC                 | L2/HVAC | kalk-top              | OZC engines                    | Tylko kalk-top               |
| `hvac.cwu`                | Ciepła woda użytkowa           | L2/HVAC | kalk-top              | CWU w OfferDTO                 |                              |
| `hvac.buffer`             | Bufor / magazyn                | L2/HVAC | kalk-top              | buffer w engineering           |                              |
| `hvac.selection`          | Dobór urządzenia               | L2/HVAC | kalk-top              | selection.pumpModel            |                              |
| `offer.trusted_ozc_hint`  | Zaufany hint OZC (ingress)     | L2      | orchestrator→kalk-top | `trusted.ozcResult` w envelope |                              |

---

## F. Dokument oferty (generator)

| ID (L2)                      | PL (L1)                      | Warstwa | Repo      | L3 (przykłady)                | Uwagi                        |
| ---------------------------- | ---------------------------- | ------- | --------- | ----------------------------- | ---------------------------- |
| `document.offer_pdf`         | Dokument oferty (PDF/DOCX)   | L1/L2   | generator | 🔒 `from-offer-dto`           | Odróżnić od oferty liczbowej |
| `document.generate_action`   | Akcja: generuj dokument      | L2      | generator | 🔒 `offer-documents/generate` |                              |
| `document.input_mapper`      | Mapowanie OfferDTO → szablon | L2      | generator | 🔒 `map_from_offer_dto`       |                              |
| `document.offer_dto_payload` | Payload OfferDTO w żądaniu   | L2      | generator | 🔒 `offerDto` w body          |                              |

---

## G. Operator, Daszek, decyzje (gmail-agent Node A/B)

| ID (L2)                    | PL (L1)                      | Warstwa | Repo               | L3 (przykłady)                  | Uwagi                                             |
| -------------------------- | ---------------------------- | ------- | ------------------ | ------------------------------- | ------------------------------------------------- |
| `operator.surface.daszek`  | Panel operatora (Daszek)     | L1      | gmail-agent Daszek | plugin Daszek                   | Projekcja                                         |
| `operator.projection_v2`   | Projekcja v2 (Node A)        | L2      | Daszek             | 🔒 `store-v2.php` paths         | Nie SoT                                           |
| `operator.bridge_queue`    | Kolejka mostu Node A→B       | L2      | Daszek             | 🔒 `bridge_queue.jsonl`         |                                                   |
| `operator.case_archive`    | Archiwum spraw (operator)    | L2      | Daszek (Node A)    | 🔒 `operator_case_archive.json` | Overlay UI; nie kasuje Postgres; P1 sync z Node B |
| `operator.feedback`        | Informacja zwrotna operatora | L2      | gmail-agent        | feedback_events                 |                                                   |
| `decision.action_proposal` | Propozycja akcji             | L2      | gmail-agent        | 🔒 `action_proposal.v1`         | P1: tylko przez pipeline                          |
| `decision.policy_proposal` | Propozycja z polityki        | L2      | gmail-agent        | 🔒 `policy_action_proposal.v1`  |                                                   |
| `decision.adjudication`    | Rozpatrzenie (adjudication)  | L2      | gmail-agent        | adjudication\_\*                |                                                   |
| `operator.skrzat_ask`      | Zapytanie Skrzat             | L2      | gmail-agent        | 🔒 `/skrzat/ask`                | Read na packu                                     |
| `hitl.case_decision`       | Decyzja na sprawie           | L1      | gmail-agent        | bridge→reconcile                | Osobny gate od oferty Cieplo                      |

---

## H. RAG i wiedza

| ID (L2)                       | PL (L1)                    | Warstwa | Repo | L3 (przykłady)                          | Uwagi                  |
| ----------------------------- | -------------------------- | ------- | ---- | --------------------------------------- | ---------------------- |
| `rag.advisory_chat`           | Czat doradczy              | L1      | RAG  | 🔒 `/chat`                              | Nie gate oferty        |
| `rag.knowledge_base`          | Baza wiedzy (HVAC)         | L2      | RAG  | Chroma 🔒 `hvac_knowledge`              | ≠ pamięć sprawy        |
| `rag.offer_context`           | Kontekst oferty (w czacie) | L2      | RAG  | 🔒 `offer_context`                      | Caller-supplied        |
| `rag.case_context`            | Kontekst sprawy (w czacie) | L2      | RAG  | 🔒 `case_context`                       | ≠ live CaseContextPack |
| `rag.cieplo_ingress_disabled` | Ingress Cieplo wyłączony   | L2      | RAG  | 🔒 `CIEPLO_INGRESS_ENABLED=0`           | D1                     |
| `rag.generator_bridge`        | Most do generatora         | L2      | RAG  | `build_generator_request_from_offer_v1` | Opcjonalny PDF         |

---

## I. Korelacja, trace, ingress (cross-cutting)

| ID (L2)                      | PL (L1)                    | Warstwa | Repo                   | L3 (przykłady)              | Uwagi              |
| ---------------------------- | -------------------------- | ------- | ---------------------- | --------------------------- | ------------------ |
| `ingress.gmail_poll_cieplo`  | Odpytywanie Gmail (Cieplo) | L2      | orchestrator           | worker CLI                  | D3 dual poller     |
| `ingress.gmail_case`         | Intake sprawy Gmail        | L2      | gmail-agent            | gmail_intake, signal_worker |                    |
| `correlation.message_gmail`  | Id wiadomości Gmail        | L2      | oba                    | 🔒 `message_id`             | link_type P0       |
| `correlation.trace_pipeline` | Trace przebiegu Cieplo     | L2      | orchestrator, kalk-top | 🔒 `trace_id`, `traceId`    |                    |
| `gap.p0_case_workflow`       | Luka: sprawa ↔ zlecenie    | L2      | knowledge              | brak FK                     | Wymaga registry    |
| `gap.d2_gmail_to_calc`       | Luka: sprawa → calc        | L2      | knowledge              | brak calculate-offer z GA   | Ręczny/trigger API |
| `readapi.context_pack`       | API: pakiet kontekstu      | L2      | gmail-agent            | 🔒 GET context-pack         | EVOLUTION B        |

---

## J. Terminy zastrzeżone (nie używać w nowym znaczeniu)

| Unikaj (L1/L2)               | Powód                    | Użyj zamiast                                 |
| ---------------------------- | ------------------------ | -------------------------------------------- |
| **lead** (samotnie w UI)     | 3 znaczenia (#1,#2,#12)  | zlecenie Cieplo / dane kontaktu w kalkulacji |
| **klient w RAG** jako SoT    | RAG nie ma identity      | tożsamość w registry (P0)                    |
| **oferta** bez kwalifikatora | offer vs PDF vs snapshot | oferta liczbowa / dokument PDF               |
| **sprawa** dla workflows     | Błędny mapping           | sprawa mailowa vs zlecenie Cieplo            |
| **user** dla klienta         | Kolizja z auth RAG       | klient / operator                            |

---

## Relacje (diagram tekstowy)

```text
identity (1) ──< engagement (N) >── correlation_link ──> case.mail_case_id | cieplo.workflow_id | message_id | trace

cieplo.workflow ──produces──> offer.calc_request ──> offer.numeric_offer (OfferDTO)
offer.numeric_offer ──copied──> cieplo.offer_snapshot (offer_json)
offer.numeric_offer ──renders──> document.offer_pdf

case.mail_case ──SoT──> mailbox_memory ──projects──> operator.projection_v2
operator.feedback ──bridge──> case.reconcile ──updates──> case.context_pack
```

---

## Indeks mapowania L1 → L2 (szybka ściąga operatora)

| Po polsku (L1)           | ID (L2)                                           |
| ------------------------ | ------------------------------------------------- |
| Klient                   | `os.identity` / `identity.contact_email`          |
| Zaangażowanie (docelowo) | `os.engagement`                                   |
| Sprawa mailowa           | `case.mail_case`                                  |
| Zlecenie Cieplo          | `cieplo.workflow`                                 |
| Oferta liczbowa          | `offer.numeric_offer`                             |
| Dokument PDF oferty      | `document.offer_pdf`                              |
| Asystent wiedzy          | `rag.advisory_chat`                               |
| Decyzja operatora        | `hitl.case_decision` / `decision.action_proposal` |

---

**Następny plik:** szczegóły tokenów L3 → [`ALIAS_REGISTRY.yaml`](ALIAS_REGISTRY.yaml)
