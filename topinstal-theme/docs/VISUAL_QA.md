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

