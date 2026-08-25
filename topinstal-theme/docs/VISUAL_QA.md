# Visual QA

Minimum browser proof for design changes:

- mobile: 360-390px wide;
- tablet: around 768px wide;
- desktop: 1366-1440px wide.

Check:

- final URL is the intended staging/preview URL;
- no verification interstitial;
- DOM contains expected header, nav, main content and footer;
- no horizontal overflow;
- images are loaded;
- menu opens/closes on mobile;
- CTA links resolve to intended URLs;
- calculator/generator/chat shortcodes still render where present;
- console has no new application errors;
- network has no unexpected 4xx/5xx for theme assets.

Screenshot is evidence, not the whole proof. Record DOM assertions and interaction
results with the screenshot path.

## Current Local Preview Proof

Local preview target:

```text
http://localhost:8097
```

Representative artifact directory:

```text
.artifacts/topinstal-theme-preview-20260825/
```

The current foundation has been proven locally with:

- WordPress runtime active on Docker;
- active `stylesheet/template=topinstal-theme`;
- browser checks for `/`, `/kalkulator/`, `/pdf/`;
- mobile `390px`, tablet `768px`, desktop `1440px`;
- header/nav/main/footer present;
- no horizontal overflow;
- no broken images;
- mobile menu open/close works;
- primary CTA points to `/kalkulator/`;
- no verification interstitial;
- shortcode placeholders remain in page body, not in hero lead.

This is `FRESHLY_PROVEN_LOCALLY`, not `DEPLOYED`.
