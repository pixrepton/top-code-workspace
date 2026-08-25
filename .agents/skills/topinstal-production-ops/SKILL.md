---
name: topinstal-production-ops
description: Use for TOP-INSTAL production operations involving Hetzner, Hostido/WordPress, converter-vps, Caddy, DNS, cieplo-worker, systemd, SSH, or production secrets. Not for ordinary local-only coding.
---

# TOP-INSTAL Production Ops

This skill preserves procedural lessons from the first production deployment of
`converter-vps`, WordPress control, and `cieplo-worker`. It is adaptive guidance,
not a command script.

## Use When

- Diagnosing, deploying, rolling back, or proving TOP-INSTAL production runtime.
- Work touches Hetzner `aios1`, Hostido/WordPress, `converter-vps`, Caddy, DNS,
  `cieplo-worker`, systemd timers, production secrets, or public HTTPS.
- A local change must be mapped to live WordPress/plugin/runtime behavior.

## Do Not Use When

- Pure local repo tests or documentation edits with no production implication.
- HVAC calculation or OfferDTO ownership questions; route those to `kalk-top`.
- Gmail-agent/Daszek work that does not cross into TOP-INSTAL production runtime.
- External provider documentation only; use the current provider docs directly.

## Canonical State First

Open the current production runbook before acting:

`top-instal-generator/docs/PRODUCTION_AGENT_OPERABILITY.md`

Treat it as an inventory and control-surface entrypoint, not as runtime proof.
Verify cheap drift-prone facts live before mutating production: DNS, listeners,
systemd state, container images, plugin state, and public endpoints.

## Hard Safety

- Do not expose Gotenberg, converter `8080`, or historical `8443` directly to
  the Internet. Public ingress is Caddy HTTPS to `127.0.0.1:8080`.
- Do not weaken security to make a smoke pass: no public `8080`, no open `3000`,
  no `StrictHostKeyChecking=no`, no guessed DNS, no copied private keys.
- Do not put runtime secrets in Git, tracked Nginx config, README, shell output,
  task checkpoints, or final reports.
- If a production secret appears in a command, output, transcript, or tracked
  file, rotate it and then synchronize every consumer before claiming recovery.
- Do not treat WordPress Agent API Key and converter `X-Converter-Token` as the
  same secret.
- Do not enable or keep enabled a polling timer until the whole downstream path
  it depends on has a current proof.

## Preferred Patterns

- Prefer SSH/CLI for host runtime operations. Use provider APIs only for
  provider-owned lifecycle operations such as firewall, DNS, server, IP, or
  snapshot changes.
- On Hostido, prefer SSH plus WP-CLI for deployment and option inspection when
  available. Use bounded REST only for the specific admin operations it owns.
- Before plugin deployment, create a rollback-safe backup of the active plugin
  directory. Deploy a controlled source state, not an arbitrary dirty tree.
- Keep runtime artifacts minimal: deploy only files needed by the service, not a
  whole product repo, unless that is the proven runtime shape.
- For Windows -> SSH -> Linux work, avoid long nested one-liners when quoting,
  secrets, heredocs, or `$` expansion matter. Send a short script over stdin or
  execute a remote script on the target host.
- Load secrets on the target side from approved secret files. Pass them between
  systems without printing them.

## Proof Ladder

- Converter: health is not enough. Require auth failure proof, method proof,
  external-port proof, real DOCX to PDF, non-empty body, `%PDF-`, and healthy
  container/log state.
- Public HTTPS: prove DNS resolves to the intended VPS, Caddy is active, TLS
  verifies, and the same DOCX to PDF smoke passes through the public URL.
- WordPress: prove the live plugin has the expected route, fail-closed auth,
  safe config metadata, and real generator output as PDF. A REST route existing
  locally is not a production deploy proof.
- Cieplo: run preflight for DB, Gmail, kalk-top, generator, and SMTP; then use a
  safe fixture/override route; then verify DB state, email sent marker, PDF
  magic/size, and a successful systemd poll before relying on the timer.
- Restart safety: after deployment, prove restart/down-up behavior where the
  service is expected to survive restarts.

## Diagnostic Heuristics

- A live WordPress REST `404` after a local commit usually means the plugin was
  not deployed or the route was not bootstrapped in the active plugin.
- Host-level UFW allowing `80/443` does not prove public reachability; cloud
  firewall rules can still block Caddy/ACME.
- Caddy certificate failure often means DNS or firewall, not Caddy syntax.
- Manual runs as a service user may fail to read `600` env files even though
  systemd works; systemd reads `EnvironmentFile` before dropping privileges.
- WordPress auth headers may arrive via server variables rather than the helper
  path expected locally; prove the live header path.
- `DOCUMENT_READY_DEGRADED` or fallback DOCX from the generator is not PDF
  success; treat it as converter integration failure until proven otherwise.

## Anti-Patterns

- Chaining several interpreters in one command while also handling secrets.
- Treating `docker compose up -d`, `/health`, or HTTP 200 as complete proof.
- Copying an old runtime because the hardened package was not found.
- Changing public exposure instead of fixing DNS, Caddy, firewall, or token
  wiring.
- Assuming two historical IPs are the same machine or bypassing a changed SSH
  fingerprint to investigate them.
- Recording incident-specific escape characters as a rule; preserve the higher
  lesson: reduce interpreter layers and prove on the target runtime.

## Report

- State which facts came from the runbook and which were freshly verified.
- Separate `FACT`, `INVARIANT`, `PREFERRED PATTERN`, `HEURISTIC`,
  `ANTI-PATTERN`, and `EPHEMERAL`.
- Report proof strength without promoting historical or local evidence to
  current production proof.
- List secret locations and rotation paths, never secret values.
