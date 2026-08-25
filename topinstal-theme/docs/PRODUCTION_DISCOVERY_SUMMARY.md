# Production Discovery Summary

Status: read-only production discovery from Hostido SSH/WP-CLI on 2026-08-25.

## Current WordPress

- WP root: `/home/host707245/domains/topinstal.com.pl/public_html`.
- DB prefix: `wpnh_`.
- Home/siteurl: `https://topinstal.com.pl`.
- Permalinks: `/%postname%/`.
- Front page mode: static page, `page_on_front=7`.
- Active theme: `hello-elementor` 3.4.9.
- PHP: 8.3.31.
- Active presentation stack: Elementor, Pro Elements, Header Footer Elementor,
  Ultimate Post Kit, AMP, LiteSpeed Cache.
- Active functional TOP-INSTAL plugins observed: `gggggen`, `kkkkalk`,
  `topinstal-lead-widget`, `krzywa`.

## Frontend Ownership

| Element | Current owner | Storage | Render path |
| --- | --- | --- | --- |
| Global desktop header | Header Footer Elementor + Elementor | `elementor-hf` post ID 17 | HFE global header, excluded on page 975 |
| Global mobile header | Header Footer Elementor + Elementor | same post ID 17 | mobile-only Elementor container inside HFE header |
| Footer | Header Footer Elementor + Elementor | `elementor-hf` post ID 198 | HFE global footer |
| Main menu | WordPress nav menu `menu` | WP terms/menu items | Elementor navigation-menu widget in HFE |
| Homepage | Elementor page | page ID 7 `_elementor_data` | Elementor content; includes `[topinstal_lead_widget]` and TrustIndex shortcode |
| Montage landing page | Elementor page | page ID 975 `_elementor_data` | Elementor content; owns its own nav/header-like section because global header excludes it |
| Blog index | Elementor page | page ID 781 `_elementor_data` | Elementor + Ultimate Post Kit widget |
| Blog posts | Elementor post content | post IDs 788, 920, 949 | Elementor post template/content, page template `elementor_header_footer` |
| Calculator page | Elementor page shell | page ID 1986 | `[heatpump_calc]` shortcode |
| Configurator page | Elementor page shell | page ID 1903 | `[konfigurator]` shortcode present, registration not proven in active plugin grep |
| PDF page `/pdf` | Elementor page shell | page ID 2031 | `[top_instal_offer_generator]` shortcode from `gggggen` |
| Curve page | Elementor page shell | page ID 2175 | `[krzywa_ai]` shortcode from `krzywa` |
| Chat page | Elementor page shell | page ID 2343 | `[hvac_rag_chat]` and `[hvac_chat]`; registration not found in active plugin grep |
| Popups | Elementor | `elementor_library` IDs 477 and 2335 | Elementor popup templates |

## Functional Dependencies To Preserve

- `gggggen`: `[top_instal_offer_generator]`, REST routes under TOP-INSTAL
  generator/converter path, `/pdf` must stay functional.
- `kkkkalk`: `[heatpump_calc]`, calculator assets, REST offer/calculation routes.
- `topinstal-lead-widget`: `[topinstal_lead_widget]`, lead widget assets and REST
  routes.
- `krzywa`: `[krzywa_ai]`.
- Google Site Kit: Analytics 4 and Ads modules are active.
- LiteSpeed Cache: active; excludes include `/kalkulator`, `/konfigurator`,
  `/dobierz`, `/pdf`.
- Rank Math SEO plugin active, but page-level Rank Math title/description meta
  were empty for published pages in the sampled query.
- AMP plugin active in reader mode for pages/posts.
- Google reviews widget appears through `[trustindex no-registration=google]`.

## Elementor Dependency

Elementor is a hard current dependency:

- all published pages sampled have `_elementor_edit_mode=builder`;
- header/footer are Elementor-owned HFE templates;
- posts are Elementor-authored;
- Elementor kit ID is 480;
- Elementor popups exist.

Do not disable Elementor before page-by-page migration or an equivalent staging
proof. Deactivation would remove current header/footer, page layouts, popups,
blog layouts and several shortcode shells.

## Visual QA Access Finding

Public HTTP and Playwright access from this agent session returned a verification
interstitial with title `One moment, please...`. Full production visual QA was
not available from this environment. Future staging must expose an agent-accessible
preview URL or provide an approved browser/session path.

