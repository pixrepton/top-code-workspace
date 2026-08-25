# Oracle: Source Of Truth Boundary

The tested agent must not see this file before answering.

## Expected PASS Signals

- Identifies `kalk-top` as owner of HVAC calculation, sizing, pricing, and
  `OfferDTO`.
- Identifies `top-instal-generator` as a document renderer / consumer of
  `OfferDTO`, not the owner of pricing logic.
- Keeps `cieplo-orchestrator` as a separate Cieplo pipeline with its own DB, not
  a second case Source of Truth.
- Keeps `daszek` as projection / bounded HITL, not a write Source of Truth.
- Names producer/consumer chain rather than patching the PDF symptom first.
- Cites workspace sources such as root `AGENTS.md`, `CODEX_EXECUTION_MAP.md`,
  target repo `AGENTS.md`, and relevant contracts/readmes.
- States that current runtime behavior still requires runtime discovery if the
  question is about what is happening live.

## Failure Signals

- Starts by editing the generator because the symptom is in a PDF.
- Duplicates pricing logic in a consumer.
- Treats Cieplo or Daszek as the owner of offer calculation.
- Gives ownership claims without workspace source paths.

