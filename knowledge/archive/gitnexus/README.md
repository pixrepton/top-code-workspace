# GitNexus — konfiguracja grupy workspace

## Stable Ops (5 repo + produkcja)

| Artefakt                                                                   | Rola                                                               |
| -------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| [`stable-ops/STABLE_OPS_MEMORY.md`](stable-ops/STABLE_OPS_MEMORY.md)       | Pamięć agenta — Node A/B, Daszek, RAG backend/widget, spięcie prod |
| [`stable-ops/workspace-manifest.yaml`](stable-ops/workspace-manifest.yaml) | Manifest maszynowy (ścieżki, hosty, krawędzie)                     |
| [`stable-ops/sync-workspace.ps1`](stable-ops/sync-workspace.ps1)           | `reindex-workspace.ps1` + `group sync` + status                    |

```powershell
cd stable-ops
.\sync-workspace.ps1          # pełny cykl
.\sync-workspace.ps1 -StatusOnly
```

**Jeden graf:** `unified-workspace/analyze-unified-workspace.ps1` → registry `topinstal-unified`.

**Git hooki:** `install-git-staleness-hooks.ps1` (CLI 1.6.5 bez natywnego hooks install).

**Understand Anything:** [`../docs/UNDERSTAND_ANYTHING.md`](../docs/UNDERSTAND_ANYTHING.md) · stos: [`../docs/CODE_INTELLIGENCE_STACK.md`](../docs/CODE_INTELLIGENCE_STACK.md).

```powershell
.\run-understand-full-gmail-agent.ps1 -StartDashboard  # all-in-one pilot Node B
.\bootstrap-understand-plugin.ps1      # tylko build core
.\run-understand-pilot-gmail-agent.ps1 # Phase 1-1.5
python .\run-understand-phase2-7.py    # Phase 2-7 (graf)
```

## Preflight

```powershell
.\set-gitnexus-cursor-config.ps1   # ~/.gitnexus/config.json → provider=cursor, model=auto
```

Wymagane przed `gitnexus wiki` (Plan B) i po legacy `run-wiki-all.ps1` (Cerebras nadpisuje config).

## Dwa miejsca (celowo)

| Lokalizacja                                           | Rola                                                        |
| ----------------------------------------------------- | ----------------------------------------------------------- |
| `knowledge/gitnexus/topinstal-workspace/group.yaml`   | **Edytuj tutaj** — wersja pod git / backup / review         |
| `%USERPROFILE%\.gitnexus\groups\topinstal-workspace\` | **Runtime** — `group sync`, `bridge.lbug`, `contracts.json` |

Po każdej zmianie `group.yaml` w tym folderze uruchom:

```powershell
.\sync-group.ps1 -RunSync
```

Bez kopii do `~/.gitnexus` CLI nie widzi Twoich linków.

## Trasy HTTP poza `group.yaml`

`group.yaml` ma **2 manifest linki** (Cieplo: calculate-offer + offer-documents/generate). Pozostałe trasy (gmail `context-pack`, RAG `/chat`, orchestrator ingress) — **ręczna macierz** w [`../SYSTEM_ATLAS.md`](../SYSTEM_ATLAS.md) §5.0 (tabela „Ręczna mapa integracji HTTP”). Nie dodawaj ich do `links` bez weryfikacji po `group sync`.

## Komendy

```powershell
.\verify-knowledge.ps1
gitnexus group sync topinstal-workspace --verbose
gitnexus group impact topinstal-workspace --target TopInstal_CalculateOffer_UseCase --repo core/kalk-top --direction upstream --max-depth 4 --cross-depth 1
```

Impact **sekwencyjnie** po sync (równoległe runy mogą złamać `bridge.lbug`).

Indeks per-repo: patrz `../SYSTEM_ATLAS.md` §5.10.

**Pełny reindeks workspace (5 repo + sync):**

```powershell
.\reindex-workspace.ps1
```

Po sync mogą pojawić się warn `LadybugDB not initialized` przy manifest resolve — to znany porządek w CLI (pule zamknięte przed `ManifestExtractor`); `contracts.json` i 2 manifest crossLinks i tak są zapisywane.
