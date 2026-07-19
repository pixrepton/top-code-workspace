# AI-OS Runtime CLI — projekt techniczny (design only, nie zaimplementowane)

Status: projekt do przeglądu operatora. Zero kodu.

## Cel

Read-only interfejs diagnostyczny do lokalnego stacku Docker AI-OS. Bez arbitralnego shell
execution, bez root, bez generycznego SSH MCP — dokładnie jak zażądano.

## Stan zastany (audyt tej sesji)

Realne serwisy Docker Compose już istnieją i są jedynym źródłem prawdy o topologii:
- `docker-compose.cieplo-local.yml`, `docker-compose.daszek-local.yml`,
  `docker-compose.kalk-top-local.yml` (root)
- `gmail-agent/docker-compose.mailbox-memory.yml`, `docker-compose.local-vps.yml`,
  `docker-compose.vps.yml`
- `rag-chat-asystent/docker-compose.yml`, `docker-compose.agents.yml`

Nie ma jednego "docker-compose up" dla całości — usługi są komponowane per-repo. Runtime CLI
musi to respektować, nie zakładać monolitycznego stacku.

Istnieje już `scripts/verify-local-gates.ps1` (kanoniczny gate, PowerShell, zablokowany dla
agenta przez politykę operatora nawet przez Bash — potwierdzone wielokrotnie w
`OPERATOR_DECISIONS.md`). Runtime CLI **nie zastępuje** tego skryptu — to osobna rzecz
(diagnostyka on-demand vs. gate przed PASS).

## Komendy (propozycja)

```
runtime status [--repo=<name>]
  -> docker compose ps per known compose file; status/health/restart_count/uptime.
     Czysto odczytowe: `docker compose -f <file> ps --format json`.

runtime health [--repo=<name>]
  -> uderza w znane /health endpointy (gmail-agent API, rag-chat-asystent /health, itd.)
     — lista endpointów zaszyta w configu narzędzia, nie odgadywana dynamicznie.

runtime logs <service> [--tail=N] [--since=<dur>]
  -> `docker logs <container> --tail N --since <dur>`. Read-only, brak `-f` (follow) domyślnie,
     żeby uniknąć zawieszania sesji agenta na strumieniu bez końca.

runtime inspect-service <service>
  -> `docker inspect` (obraz, env keys BEZ wartości sekretnych, mounты, network, health) —
     redakcja wartości zmiennych zawierających SECRET/PASSWORD/TOKEN/KEY w nazwie,
     analogicznie do wzorca już użytego w `ObservabilityRuntime.record_event()`.

runtime config-diff <service_a> <service_b>
  -> diff dwóch `docker inspect --format {{json .Config.Env}}` po redakcji sekretów. Czysto
     mechaniczne, bez interpretacji.
```

## Twarda granica

- Brak `runtime restart`, `runtime exec`, `runtime deploy`, `runtime stop` w tym narzędziu.
  Mutacje/restart/deploy wymagają osobnej, silniej ogrodzonej ścieżki z jawną zgodą operatora
  za każdym razem — nie części tego CLI.
- Brak dowolnego `docker exec <container> <cmd>` — tylko zamknięty zestaw predefiniowanych,
  read-only subcommand.
- Brak SSH — działa wyłącznie przeciw lokalnemu Docker Desktop (`npipe:////./pipe/...` na
  Windows), zero zdalnych hostów.

## Implementacja (szkic, nie kod)

Cienki wrapper Python/PowerShell nad `docker` CLI (nie nowy SDK Docker) — spójne z zasadą
"jedno dobre narzędzie + prosty deterministyczny fallback": `docker` CLI już istnieje, działa,
jest zweryfikowane (`docker --version` → 29.5.3 w tej sesji). Runtime CLI to warstwa
redakcji+formatowania nad nim, nie reimplementacja Docker API.

## Blocking dependency

Docker Desktop musiał być ręcznie wystartowany w tej sesji (daemon nie działał na starcie) i
pozostał niestabilny podczas cold-startu (kilka minut migotania npipe). Realny smoke test
(`runtime status` na żywym `mailbox-memory-db`) nie został wykonany w tej sesji z tego powodu —
patrz Blockers w podsumowaniu I1-I8.
