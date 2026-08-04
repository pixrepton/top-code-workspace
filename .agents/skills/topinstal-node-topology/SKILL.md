---
name: topinstal-node-topology
description: Use when a task touches TOP-INSTAL physical architecture, Node A, Node B, REST bridge, Daszek, gmail-agent, kalk-top, environment variables, Docker local stack, or cross-node data flow in top-code workspace.
---

# TOP-INSTAL Node Topology

Source: adapted from `gmail-agent-legacy@f83845d`.

## Use When

- Diagnosing where code or data lives: Node A vs Node B.
- Editing bridge, REST, auth, paths, deployment, `.env`, or Daszek transport.
- Cross-repo work touching multiple nested Git repositories.

## Do Not Use When

- Pure local unit test in one repo with no topology implication.

## Workspace layout (current)

| Component              | Repo / path                   | Role                                              |
| ---------------------- | ----------------------------- | ------------------------------------------------- |
| Node B runtime         | `gmail-agent/`                | SoT cases, policy, execution, mailbox memory      |
| Node A UI              | `daszek/`                     | Projection-only operator UI, bounded HITL         |
| HVAC / OfferDTO        | `kalk-top/`                   | Sizing, pricing, OfferDTO owner                   |
| RAG backend            | `rag-chat-asystent/`          | Ingest, retrieval                                 |
| RAG widget             | `rag-widget/`                 | WordPress client                                  |
| Knowledge / governance | `knowledge/`                  | Cross-repo contracts, decisions (not runtime SoT) |
| Harness                | `scripts/`, `.agents/skills/` | Workspace-level only                              |

## Non-negotiables

- Node A = WordPress/Daszek operator surface; projection-only.
- Node B = `gmail-agent` Python, Postgres, workers, policy.
- No shared filesystem between Node A and Node B in production shape.
- Communication is HTTP/REST bridge or explicit protocol.
- `kalk-top` owns OfferDTO — do not duplicate in `gmail-agent`.
- Local files ≠ live production proof.

## Minimal procedure

1. Name the owning repo and node.
2. Name the transport (REST bridge, API, etc.).
3. Reject invalid filesystem assumptions.
4. Classify Gate A (repo tests) vs Gate B (stack smoke / browser / operator).
5. For Docker: verify build/recreate when code is image-baked.

## Report

- Node: A / B / both via bridge.
- Owning repo(s).
- Transport.
- Filesystem assumptions: valid / invalid.
- Gate: local only / stack smoke / operator proven / not claimed.
