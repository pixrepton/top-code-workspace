# AI-OS Replay Harness — MVP projekt techniczny (design only, nie zaimplementowane)

Status: projekt do przeglądu operatora. Zero kodu.

## Kontekst zastany

`OPERATOR_DECISIONS.md` dokumentuje, że eval/replay tooling dla `gmail-agent` już istnieje jako
konwencja: harness trzymany **poza repo git** (`C:\ai-os-eval-recovery-1-...\harness\`), z
"safe shim" tool registry, który zapisuje ale nie wykonuje `propose_mutation`, żeby żaden replay
nie mógł pisać do współdzielonej żywej bazy Postgres. To jest już sprawdzony, operator-zaaprobowany
wzorzec bezpieczeństwa — MVP Replay Harness powinien go kontynuować, nie wynajdywać nowego.

Trzy generacje harnessu już istniały (`run_baseline.py` → `run_recovery.py`/`scoring.py`) z
udokumentowanymi lukami pomiarowymi (brak przechwytywania `understanding_output`, brak odczytu
`snapshot_delta`, brak rubric scoringu) — MVP powinien czerpać z tych lekcji, nie powtarzać ich.

## Model docelowy (z brief'u operatora)

```
realny input
  -> sanitizacja
  -> izolowane środowisko
  -> replay
  -> invariants
  -> before/after comparison
```

## Rozbicie na komponenty

### 1. Capture / sanitization
- Źródło: realny `CanonicalSignal` payload z `telemetry_events.jsonl` (per-run local mirror,
  patrz Diagnostic MCP design) lub bezpośrednio z Postgres `mailbox_memory_signals`.
- Sanitizacja: usunięcie/maskowanie PII (adresy email poza domeną testową, numery telefonów,
  nazwiska) — wzorcowa redakcja już częściowo istnieje (`_redact_for_logging` w
  `agent_runtime/business_pulse.py`, do zweryfikowania czy pokrywa pełny zakres pól potrzebny
  tutaj, nie do ślepego reużycia bez audytu).

### 2. Deterministic fixture
- Zamrożony JSON per case, wersjonowany (podobnie jak `corpus-v1.json` z EVAL-1) — nie żywe
  połączenie do produkcyjnej bazy podczas replay.

### 3. Isolated replay
- **Musi** używać "safe shim" tool registry (wzorzec z `EVAL-1`/`EVAL-RECOVERY-1`): realne
  handlery dla narzędzi read/decision, zapisany-ale-niewykonany rekord dla `propose_mutation`.
  Zero ryzyka zapisu do współdzielonej bazy.
- Osobny, unikalny Postgres compose project/volume/port — dokładnie zgodnie z aktywną decyzją
  operatora `OPERATOR_DECISIONS.md` 2026-07-14 ("Postgres proof izolacja: unikalny
  project/volume/port, nie sama nazwa kontenera") — to jest już wiążąca reguła, nie propozycja.

### 4. Invariants
- Zestaw deterministycznych assercji per replay (nie LLM-as-judge dla samych inwariantów):
  np. "brak nowego case_id", "decision_key niezmieniony jeśli input niezmieniony",
  "execution_result.status nigdy 'unknown'". LLM-judge (jeśli w ogóle) tylko dla jakości
  semantycznej draftu, oddzielony od twardych inwariantów.

### 5. Before/after comparison
- Diff strukturalny (nie tekstowy) dwóch przebiegów tego samego fixture na dwóch wersjach kodu
  — analogiczne do `EVAL-1.1` frozen-corpus-rerun, które już udowodniło swoją wartość
  (wykrycie regresji `generate_draft_reply` argument-schema).

## Czego MVP NIE robi

- Nie zastępuje istniejącego `scripts/verify-local-gates.ps1`.
- Nie zastępuje pełnego EVAL harnessu (corpus/rubric/scoring) — to osobny, większy system,
  eval tooling pozostaje poza repo git zgodnie z ustaloną konwencją 3 sesji.
- Nie replayuje przeciw produkcyjnej bazie ani produkcyjnym providerom LLM bez jawnej zgody
  (koszt/limity — patrz udokumentowane w `OPERATOR_DECISIONS.md` problemy z Groq daily quota
  podczas gęstych sesji replay).

## Blocking dependency

Wymaga działającego lokalnego Postgres (patrz I1/Docker blocker) do zaprojektowania i
przetestowania izolacji volume/port. Nie rozpoczęty w tej sesji poza tym dokumentem — zgodnie z
jawnym poleceniem "nie wdrażaj całej trójki bez osobnej decyzji po projekcie technicznym".
