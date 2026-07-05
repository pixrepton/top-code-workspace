# RFC: P1.4 Merge DB + P1.5 Rename program

| Pole       | Wartość                               |
| ---------- | ------------------------------------- |
| **Data**   | 2026-05-22                            |
| **Status** | draft                                 |
| **Wymaga** | decyzja właściciela (OWNER_DECISIONS) |

## P1.4 — Merge `mailbox_memory` + `cieplo_worker`

### As-Is

- Dwa magazyny w jednym Postgres (staging), brak FK case↔workflow przed P0.
- P0: `correlation_links` + `EngagementSnapshot` = federated read-model.

### Warianty

| ID  | Opis                                               | Koszt  | Ryzyko  |
| --- | -------------------------------------------------- | ------ | ------- |
| A   | Zostawić federated + registry (status quo post-P0) | niski  | niskie  |
| B   | Jedna schema / widoki SQL                          | średni | średnie |
| C   | Pełny merge + migracja historyczna                 | wysoki | wysokie |

**Rekomendacja:** A do końca P1; B/C tylko po metrykach pokrycia registry.

## P1.5 — Rename (`case_id`, `workflows`, `lead`, OfferDTO)

### Zasady

- [`ALIAS_REGISTRY.yaml`](../nomenclature/ALIAS_REGISTRY.yaml) `immutable: true` dla L3.
- Kolejność: L2 docs → API v2 (`cieplo_workflow_id` już w API v2) → migracje L3 per repo.

### Zakres per repo (fale)

1. knowledge + nomenclature
2. orchestrator (`lead_id` → display `cieplo_workflow_id`)
3. gmail-agent (stopniowo, bez łamania REST)
4. kalk-top / generator (OfferDTO — **osobny RFC**)
5. RAG (tylko copy L1)

## Akceptacja właściciela

- [ ] Merge wariant: A / B / C
- [ ] Rename wave 1 termin: \_\_\_
