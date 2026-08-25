# TOP-INSTAL Theme

Minimal, agent-manageable WordPress theme foundation for migrating
`topinstal.com.pl` away from page-builder-owned presentation.

## Current Intent

WordPress stays the CMS and backend. Existing functional plugins keep owning
calculators, generator, lead widget, RAG chat and other business functions. This
theme owns presentation: layout, header, footer, reusable sections, responsive
behavior, CSS, JS and design tokens.

## Structure

```text
topinstal-theme/
+-- style.css
+-- functions.php
+-- theme.json
+-- header.php
+-- footer.php
+-- front-page.php
+-- page.php
+-- single.php
+-- index.php
+-- inc/
|   +-- setup.php
|   +-- template-tags.php
+-- template-parts/
|   +-- site-header.php
|   +-- site-footer.php
|   +-- page-hero.php
|   +-- post-card.php
+-- assets/
|   +-- css/
|   |   +-- tokens.css
|   |   +-- main.css
|   +-- js/
|       +-- site.js
+-- preview/
+-- docs/
```

## Boundaries

CMS-managed: page titles, copy, images, SEO metadata, testimonials, FAQs, contact
data when exposed through WordPress settings/theme mods, and existing page
content.

Code-managed: header/footer composition, section layouts, components, design
tokens, breakpoints, interaction states and theme-level rendering.

Plugin-managed: `[heatpump_calc]`, `[konfigurator]`, `[top_instal_offer_generator]`,
`[topinstal_lead_widget]`, `[krzywa_ai]`, `[hvac_rag_chat]`, `[hvac_chat]` and
their REST/API behavior.

## Local Static Proof

Run from this folder or workspace root:

```powershell
php -l topinstal-theme/functions.php
php -l topinstal-theme/inc/setup.php
php -l topinstal-theme/inc/template-tags.php
php -l topinstal-theme/header.php
php -l topinstal-theme/footer.php
php -l topinstal-theme/front-page.php
php -l topinstal-theme/page.php
php -l topinstal-theme/single.php
php -l topinstal-theme/index.php
```

Runtime proof requires a WordPress staging install or preview mechanism. Do not
use production theme activation as a design preview.
