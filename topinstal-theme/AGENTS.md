# AGENTS.md - topinstal-theme

Status: root-owned WordPress theme artifact for TOP-INSTAL website migration.

Root workspace `AGENTS.md` applies. This folder owns presentation only:

- WordPress theme structure, templates, components, CSS, JS and design tokens.
- Code-managed header, footer, layouts, responsive behavior and visual states.
- Documentation needed for future Codex-managed frontend changes.

It must not own:

- HVAC calculation, pricing, `OfferDTO`, PDF generation, RAG retrieval or lead workflow logic.
- Production WordPress content, SEO metadata, tracking configuration or plugin secrets.
- Existing public shortcode behavior such as `[heatpump_calc]`, `[konfigurator]`,
  `[top_instal_offer_generator]`, `[topinstal_lead_widget]`, `[krzywa_ai]`,
  `[hvac_rag_chat]` or `[hvac_chat]`.

Read first:

1. `README.md`
2. `docs/PRODUCTION_DISCOVERY_SUMMARY.md`
3. `docs/AGENT_FRONTEND_OPERABILITY.md`
4. `docs/DESIGN_SYSTEM.md`
5. `docs/CONTENT_MODEL.md`
6. `docs/VISUAL_QA.md`

Default proof for visual changes: local/staging browser QA at mobile, tablet and desktop widths, plus PHP syntax checks. Do not activate or deploy this theme on production without backup, preview/staging proof, cache plan and rollback path.
