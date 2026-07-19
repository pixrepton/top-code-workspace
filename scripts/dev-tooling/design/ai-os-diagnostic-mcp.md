# AI-OS Diagnostic MCP — projekt techniczny (design only, nie zaimplementowane)

Status: projekt do przeglądu operatora. Zero kodu tego MCP istnieje.

## Kluczowe odkrycie tej sesji (zmienia zakres projektu)

`gmail-agent` **nie jest greenfield** dla observability. Istnieją już dwie komplementarne,
dojrzałe warstwy:

1. `tools/gmail_audit/log_config.py` — structured JSON logging przez `ContextVar`
   (`case_id`, `engagement_id`, `signal_id`, `source_kind`, `turn`, `trace_id`),
   udokumentowane wprost jako "for Loki/ELK querying".
2. `tools/gmail_audit/observability_runtime.py` — `ObservabilityRuntime.span()`/`record_event()`
   niosące `case_id`, `message_id`, `thread_id`, `signal_id`, `trace_id`, `otel_trace_id`,
   `otel_span_id`; realny, działający kod bootstrapujący `opentelemetry-sdk` +
   `OTLPSpanExporter` (proto/http) — **obecnie wyłączony** (`GMAIL_AGENT_OTEL_ENABLED=0`),
   z lokalnym JSONL mirror (`telemetry_events.jsonl`) jako kanonicznym fallbackiem
   (`GMAIL_AGENT_OTEL_LOCAL_MIRROR_ENABLED=1`, domyślnie ON).
3. `inject_headers()` już robi W3C trace-context propagation (`opentelemetry.propagate.inject`)
   dla wywołań cross-service — infrastruktura do korelacji trace przez granice usług **już
   istnieje w kodzie**, tylko nie jest aktywnie eksportowana do żadnego backendu.

Pozostałe repo (`daszek`, `kalk-top`, `cieplo-orchestrator`, `rag-chat-asystent`) — zero
odniesień do OTel (sprawdzone grepem). Instrumentacja istnieje wyłącznie w `gmail-agent`/Node B,
zgodnie z jego rolą jako SoT/orchestration hub.

**Wniosek:** Diagnostic MCP nie musi budować korelacji od zera. Musi umieć czytać z dwóch
istniejących źródeł prawdy (JSONL mirror per-run + opcjonalnie OTLP backend, gdy operator go
włączy) i domenowo je interpretować.

## Zasada nadrzędna

MCP interpretuje domenę AI-OS. **Nie implementuje** własnego systemu logów, traces ani bazy.
Cienka warstwa nad istniejącymi źródłami prawdy.

## Źródła danych (w kolejności dojrzałości)

| Źródło | Stan dziś | Rola w MCP |
|---|---|---|
| `telemetry_events.jsonl` per run (`ObservabilityRuntime` local mirror) | Aktywne domyślnie | Podstawowe źródło dla `trace_case`/`trace_signal` — zawsze dostępne, zero zależności zewnętrznych |
| `log_config.py` structured JSON logs (stdout/docker logs) | Aktywne | Uzupełnienie o log-line-level detail, gdy JSONL mirror nie ma wystarczającego kontekstu |
| PostgreSQL (`mailbox_memory`, przez `claude_readonly`) | Istnieje, rola projektowana w tej sesji | `execution_result`, `case` state, `decision`, `identity` — stan trwały |
| OpenTelemetry/Tempo (gdy operator włączy `GMAIL_AGENT_OTEL_ENABLED=1` + collector) | Zaprojektowane w kodzie, nieaktywne | Cross-service trace, gdy dostępne — MCP musi działać też BEZ tego (graceful degrade) |
| Grafana/Loki (gdy postawione) | Nie istnieje jeszcze | Agregacja multi-run, długi retention |

## Kontrakt narzędzi (propozycja, do przeglądu operatora)

Wszystkie **read-only by default**. Żadne narzędzie nie mutuje stanu.

```
trace_case(case_id) -> chronologiczna lista eventów (JSONL mirror + Postgres decision/execution
                        rows dla tego case_id), połączona po case_id/trace_id, bez interpretacji
                        biznesowej — surowy, korelowany timeline.

trace_signal(signal_id) -> to samo dla pojedynczego sygnału (message_id/signal_id), od ingest
                            przez preclassify/reconcile/planner do execution_result.

trace_decision(decision_key) -> pełna ścieżka jednej decyzji: propozycja -> approval/rejection
                                 -> execution_result -> projekcja do Daszka. Uwaga: decision_key
                                 nie jest natywnym polem w ObservabilityRuntime.span() — MCP musi
                                 korelować przez case_id + timestamp + Postgres decision row, nie
                                 przez bezpośredni indeks eventów.

explain_case_state(case_id) -> ostatni znany EngagementSnapshotV2 (Postgres) + ostatnie N
                                eventów z JSONL mirror + ostatni execution_result. Czysta
                                projekcja istniejących danych, zero LLM-generowanej narracji
                                bez oznaczenia jako taka.

find_pipeline_failure(since, filters?) -> skan telemetry_events.jsonl (status="failed") +
                                           Postgres processing_attempts po error_code, w danym
                                           oknie czasu. Zwraca kandydatów, nie diagnozę.

show_delivery_attempts(case_id | proposal_id) -> execution_result rows (Postgres,
                                                  upsert_execution_result/fetch_execution_results)
                                                  + odpowiadające eventy JSONL, chronologicznie.

verify_convergence(case_id) -> porównanie ostatniego stanu case (Postgres) z ostatnią projekcją
                                widoczną w Daszku (przez Daszek read API, nie bezpośredni zapis do
                                jego bazy — zachowuje granicę SoT). Zwraca diff, nie werdykt.

compare_runtime_config(service_a, service_b | env_a, env_b) -> diff .env / docker inspect config
                                                                  między dwoma stanami. Czysto
                                                                  mechaniczne porównanie, bez
                                                                  interpretacji "co jest dobre".
```

## Permission model

- Domyślnie: **wyłącznie odczyt**. `PostgreSQL` przez `claude_readonly` (patrz
  `scripts/dev-tooling/create-readonly-postgres-role.sql` z tej sesji) — twarda granica na
  poziomie bazy, nie tylko instrukcja dla modelu.
- Brak dostępu do sekretów/tokenów w payloadach — MCP musi redagować pola zawierające
  `secret`/`authorization` tak jak już robi to `ObservabilityRuntime.record_event()`
  (`"secret" not in key.lower() and "authorization" not in key.lower()` — wzorzec do
  ponownego użycia, nie wynajdywania na nowo).
- Brak dostępu do produkcyjnego Postgres/VPS z tej sesji — projekt zakłada tylko local Docker
  stack (`docker-compose.mailbox-memory.yml`), zgodnie ze stability freeze.
- Zero narzędzi mutujących (`upsert_*`, `DELETE`, `UPDATE`) w kontrakcie MCP — jeśli
  kiedykolwiek potrzebne, osobny, silniej ogrodzony serwer, nie rozszerzenie tego.

## Co NIE wchodzi w zakres

- Własny storage eventów (używa istniejącego JSONL mirror + Postgres).
- Własny trace collector (używa istniejącego `opentelemetry-sdk` bootstrap, gdy operator go
  włączy — MCP tylko czyta wynik, nie zarządza pipeline'em).
- Zastępowanie Grafany jako UI — to jest narzędzie dla Claude Code, nie dashboard dla ludzi.
- `decision_key` jako natywne pole indeksu — dopóki `ObservabilityRuntime` go nie niesie
  natywnie, `trace_decision` pozostaje najsłabszym/najwolniejszym narzędziem w zestawie
  (korelacja pośrednia). Ewentualne dodanie `decision_key` do `span()`/`record_event()` w
  `observability_runtime.py` to osobna, mała zmiana w `gmail-agent` — do rozważenia przez
  operatora, nie robię tego bez polecenia (protected runtime, stability freeze).

## Blocking dependency

Realna implementacja i test wymagają: (1) działającego lokalnego stacku Docker,
(2) `claude_readonly` roli zaaplikowanej (SQL gotowy, patrz `create-readonly-postgres-role.sql`),
(3) decyzji operatora, czy `GMAIL_AGENT_OTEL_ENABLED=1` + lokalny collector mają zostać włączone
teraz, czy MCP na start ma polegać wyłącznie na JSONL mirror + Postgres (rekomendowane jako
etap 1 — mniejszy zakres, natychmiast dostępny, zero nowej infrastruktury).
