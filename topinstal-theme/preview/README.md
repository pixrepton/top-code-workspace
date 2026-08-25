# Local WordPress Preview

This is an isolated local preview for proving `topinstal-theme` in a real
WordPress runtime without touching production.

Run from `topinstal-theme/preview`:

```powershell
docker compose up -d db wordpress
docker compose run --rm wpcli bash /var/www/html/wp-content/themes/topinstal-theme/preview/bootstrap.sh
```

Default URL:

```text
http://localhost:8097
```

Stop and remove:

```powershell
docker compose down -v
```

This preview does not prove Hostido staging, production cache behavior, Elementor
migration or functional plugin internals. It proves that the theme can be
activated in WordPress and checked by a browser-controlled agent.

Proof expectations:

- verify `wp option get stylesheet` and `wp option get template` both return
  `topinstal-theme`;
- run browser QA for `/`, `/kalkulator/`, `/pdf/` at mobile/tablet/desktop;
- confirm shortcode placeholders stay in page body and do not appear in hero
  lead text;
- save representative screenshots under `.artifacts/`.
