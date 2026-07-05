# RFC: D1 — RAG a gate oferty / duplikat ingress Cieplo

| Pole              | Wartość                    |
| ----------------- | -------------------------- |
| **Data**          | 2026-05-22                 |
| **Status**        | draft                      |
| **Luka (kernel)** | `gap:D1-rag-not-in-cieplo` |

## As-Is

- Produkcja Cieplo: `cieplo-worker` → kalk-top → generator.
- RAG: `CIEPLO_INGRESS_ENABLED=0`; advisory `/chat` z opcjonalnym `offer_context`.
- P0: RAG pobiera `EngagementSnapshot` z Node B (read-only).

## To-Be (polityka)

| Reguła | Opis                                                                                   |
| ------ | -------------------------------------------------------------------------------------- |
| R1     | RAG **nie** wywołuje `calculate-offer` ani nie zapisuje `workflows`                    |
| R2     | RAG może **sugerować** duplikat ingress (advisory) na podstawie `external_key` / email |
| R3     | Gate produkcyjny oferty pozostaje w orchestrator + kalk-top                            |

## Warianty

| ID  | Opis                                    | Rekomendacja               |
| --- | --------------------------------------- | -------------------------- |
| A   | Detector advisory w RAG (log + UI hint) | **preferred**              |
| B   | RAG jako drugi ingress Cieplo           | **rejected** (D1 boundary) |

## Wpływ

RAG Chat Asystent `backend/`; brak zmiany OfferDTO.

## Akceptacja

- [ ] Zaakceptowano wariant: \_\_\_
