# CLAUDE.md — adapter Claude Code dla AI-OS TOP-INSTAL

Ten plik jest wyłącznie adapterem i routerem do dokumentów kanonicznych. Nie jest pamięcią ani Source of Truth i nie duplikuje treści z `knowledge/`.

## Start

1. Przeczytaj root `AGENTS.md`.
2. Dalszy cold-start wykonuj wyłącznie według `knowledge/INDEX.md` §Cold-Start.
3. Dla zadania dotyczącego konkretnego repo przeczytaj również jego `AGENTS.md`.

Nie odtwarzaj ani nie duplikuj kolejności cold-start poza `knowledge/INDEX.md`.

## Pamięć i SoT

Jedyna trwała pamięć operacyjna projektu:

- `knowledge/memory/OPERATOR_DECISIONS.md`
- `knowledge/memory/BACKLOG.md`
- `knowledge/memory/ACTIVE_WORKSPACE.md`
- `knowledge/memory/LAST_SESSION.md`

Nie twórz alternatywnych memory banków, reflection/transcript stores, shadow backlogów ani innych równoległych źródeł wiedzy. Nie zapisuj trwałej pamięci bez wyraźnego polecenia operatora.

## Tool routing

Dobieraj narzędzie do zadania.

### Codebase Memory MCP

Dla discovery kodu, symboli, zależności, call paths, architektury, impact i blast-radius domyślnie używaj Codebase Memory MCP przed ręcznym skanowaniem repo.

Dobieraj narzędzie do pytania:

- `search_graph` — punkt startowy dla discovery symboli i semantycznego wyszukiwania.
- `trace_path` — statyczne ścieżki wywołań i zależności.
- `query_graph` — precyzyjne pytania strukturalne i grafowe.
- `get_code_snippet` — kod konkretnego elementu znalezionego w grafie.
- `get_architecture` — przegląd struktury, języków, entry points i hotspotów repo.
- `get_graph_schema` — schemat grafu przed złożonymi zapytaniami.
- `detect_changes` — impact/blast-radius zmian względem Git.

CBM jest grafem statycznym, nie pełnotekstowym źródłem prawdy. Przejdź do `Grep/rg`, gdy:

- szukasz literału stringowego, klucza configu, nazwy pola lub parametru,
- kod korzysta z dynamicznego dispatchu albo dynamicznie budowanych URL-i,
- graf zwraca pustą ścieżkę mimo dowodów rzeczywistego użycia,
- potrzebujesz wyczerpującej listy wszystkich tekstowych wystąpień.

Dla znanych plików, konfiguracji i dokumentacji używaj bezpośrednio `Read`.

Przy blast-radius traktuj CBM jako analizę zależności, a `Grep/rg` jako kontrolę kompletności tam, gdzie zmieniana semantyka może występować również poza symbolami grafu.

Nie interpretuj braku statycznej krawędzi jako dowodu braku rzeczywistej integracji. Weryfikuj dynamiczne przepływy kodem, konfiguracją i runtime proof.

### Read / Grep / rg

Używaj bezpośrednio dla znanych plików, dokumentacji, YAML/JSON/config, dokładnych literałów, prostego wyszukiwania tekstowego i finalnej weryfikacji implementacji.

Nie zastępuj nimi domyślnie CBM przy analizie zależności, call paths i architektury.

### Playwright MCP

Używaj dla rzeczywistych flow Daszka/UI, E2E, DOM, formularzy, interakcji i zachowania aplikacji w przeglądarce.

### OpenAI Docs MCP

Używaj dla aktualnej dokumentacji OpenAI API i produktów OpenAI. Nie opieraj implementacji aktualnych API na pamięci modelu, gdy dostępne jest źródło oficjalne.

### Bash

Używaj do deterministycznej walidacji, testów, lintowania, compile checks, proofów, inspekcji Git i istniejących gate'ów repo.

LLM interpretuje i planuje; runtime, testy i proofy dostarczają dowodów.

## Stability freeze

Aktywne decyzje z `knowledge/memory/OPERATOR_DECISIONS.md` mają pierwszeństwo przed nieaktualną dokumentacją.

Chroniony runtime obejmuje m.in.:

- identity,
- feed v3,
- Row4a / Row4b,
- auth `/tasks*`,
- idempotencję send/reject,
- konwergencję UI.

Zmiany wykonuj wyłącznie przez:

diagnoza → root cause → test RED → minimalny fix → test GREEN → pełna regresja → runtime proof/parity → review.

Nie rozszerzaj scope bez potrzeby. Nowe problemy klasyfikuj jako blocker wymagający minimalnego fixu teraz albo backlog.

`gmail-agent/docs/runbooks/LAST_PROVEN_STATE.md` aktualizuj dopiero po rzeczywistym PASS.

## Epistemika i proof discipline

Nie uznawaj rozwiązania za poprawne tylko dlatego, że kod wygląda poprawnie.

Rozróżniaj:

- deklarowaną architekturę,
- implementację,
- konfigurację,
- stan danych,
- rzeczywiste zachowanie runtime,
- dowód testowy lub produkcyjny.

Aktualny, odtwarzalny dowód zachowania ma pierwszeństwo przed nieaktualną dokumentacją i założeniami. Nie przedstawiaj częściowego proofu jako pełnego PASS.

## Zakazy

- Nie twórz nowej pamięci, memory banków ani shadow backlogów.
- Nie zapisuj planów poza workspace bez wyraźnego polecenia.
- Nie duplikuj cold-start ani kanonicznych zasad projektu.
- Nie obchodź granic SoT poszczególnych usług.
- Nie przenoś logiki domenowej między komponentami dla wygody.
- Nie dodawaj nowych warstw, frameworków ani workflow bez konkretnej potrzeby.
- Nie wykonuj commit, push, deploy ani pracy na VPS bez wyraźnego polecenia operatora.

## Shell discipline

Workspace root jest już katalogiem roboczym.

Nie używaj `cd`, jeśli nie jest konieczne. Preferuj krótkie, atomowe komendy zamiast `&&`, `;` i wieloliniowego Basha, aby istniejące permissions mogły je bezpiecznie rozpoznawać.

Nie używaj destrukcyjnych poleceń ani szerokich operacji Git bez wyraźnego polecenia operatora.

## Repo-level AGENTS.md

- `gmail-agent/AGENTS.md` — Node B; mailbox/case runtime; operacyjny SoT spraw, decyzji i wykonania.
- `daszek/AGENTS.md` — Node A; projection-only UI; bounded HITL.
- `kalk-top/AGENTS.md` — właściciel HVAC, sizingu, pricingu i `OfferDTO`.
- `cieplo-orchestrator/AGENTS.md` — osobny pipeline/worker Cieplo z własną bazą; nie drugie SoT spraw.

Przy zadaniach cross-repo najpierw określ wpływ na kontrakty i zachowaj granice ownership oraz SoT.

## Subagenci

Domyślnie prowadź jeden kontrolowany tok pracy.

Uruchamiaj subagentów tylko przy realnej korzyści, np. niezależnym dużym discovery, adversarial review lub równoległym researchu bez mutacji wspólnego stanu.

Przed uruchomieniem określ krótko rolę i zakres subagenta. Finalna synteza, decyzja architektoniczna i odpowiedzialność za poprawność pozostają w głównym toku pracy.
