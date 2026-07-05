# TOP-INSTAL — nomenclature governance (faza 2)

> **Status:** 2026-05-23 · **P0 registry:** wdrożony w kodzie (gmail-agent + orchestrator + Daszek proxy + RAG env-gated) · **Zero rename** kotwic L3 · **Daszek 1.2.2:** `operator.case_archive` w słowniku
> **Poprzednik:** [`discovery/2026-05-22-nomenclature-discovery-report.md`](../discovery/2026-05-22-nomenclature-discovery-report.md) (faza 1 As-Is)

## Cel

Jeden spójny **język operacyjny OS** (warstwy 1–3) jako fundament pod:

- P0 Identity + Engagement Registry + `correlation_links`
- P1 unified event spine
- P1 Decision Pipeline jako runtime gate
- P2 RAG jako warstwa wiedzy (advisory)

**Nie** jest to plan masowego refaktoru nazw w kodzie.

## Trzy warstwy (obowiązuje wszystkie nowe dokumenty i RFC)

| Warstwa | Kod  | Kto używa                             | Zasada                                             |
| ------- | ---- | ------------------------------------- | -------------------------------------------------- |
| **L1**  | `L1` | Operator, szkolenie, UI (PL)          | 100% ujednolicone w dokumentacji i nowym UI        |
| **L2**  | `L2` | Kontrakty OS, RFC, nowe API, registry | Kanon EN; **dokładamy** obok zamrożonych kotwic    |
| **L3**  | `L3` | Implementacja per repo                | **Frozen** tam, gdzie `immutable: true` w registry |

## Zawartość folderu

| Plik                                                           | Rola                                                         |
| -------------------------------------------------------------- | ------------------------------------------------------------ |
| [`CANONICAL_GLOSSARY.md`](CANONICAL_GLOSSARY.md)               | Słownik kanoniczny (~100 pojęć): L1 PL + L2 ID + zakres repo |
| [`ALIAS_REGISTRY.yaml`](ALIAS_REGISTRY.yaml)                   | Mapowanie tokenów L3 → L2 (`immutable`, `ui_label_pl`)       |
| [`COLLISION_POLICIES.md`](COLLISION_POLICIES.md)               | 12 kolizji z polityką: zostaw / alias / UI v2 only           |
| [`P0_CORRELATION_LINK_TYPES.md`](P0_CORRELATION_LINK_TYPES.md) | `link_type` dla registry + mapowanie As-Is tokenów           |
| [`OWNER_DECISIONS.md`](OWNER_DECISIONS.md)                     | 3 decyzje właściciela + rekomendacja pod „jeden OS”          |
| [`GOVERNANCE_RULES.md`](GOVERNANCE_RULES.md)                   | Zasady dla agentów i nowych modułów                          |

## Kolejność czytania (agent / architekt)

1. `CANONICAL_GLOSSARY.md` (sekcja „Jak czytać”)
2. `ALIAS_REGISTRY.yaml` (przy implementacji mapowania)
3. `COLLISION_POLICIES.md`
4. `OWNER_DECISIONS.md` — **blokuje RFC implementacyjne** do zaznaczenia statusu
5. `P0_CORRELATION_LINK_TYPES.md` — szablon pod `knowledge/rfc/P0-correlation-registry.md`

## Powiązania

- [`SYSTEM_ATLAS.md`](../SYSTEM_ATLAS.md) §3–§4, §5.2
- [`EVOLUTION_BOUNDARIES.md`](../EVOLUTION_BOUNDARIES.md)
- [`TOPINSTAL-KERNEL-GRAPH.yaml`](../TOPINSTAL-KERNEL-GRAPH.yaml)

## Następny krok (po P0 Gate B)

- E0 ops: [`deploy/p0-ensure-vps-services.sh`](../../gmail-agent/deploy/p0-ensure-vps-services.sh), proof [`artifacts/proof-packs/p0-correlation-registry-gateb-2026-05-22.md`](../artifacts/proof-packs/p0-correlation-registry-gateb-2026-05-22.md)
- P1 RFC: [`rfc/P1-unified-event-spine.md`](../rfc/P1-unified-event-spine.md), [`rfc/P1-decision-pipeline-gate.md`](../rfc/P1-decision-pipeline-gate.md), D1/D2, merge/rename
- Operator unlink UI (P1.3)
