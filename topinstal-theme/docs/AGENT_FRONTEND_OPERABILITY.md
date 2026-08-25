# Agent Frontend Operability

## Owner

The theme owns presentation. Functional plugins keep owning business behavior.
Future Codex work should start here for visual/layout changes:

1. `AGENTS.md`
2. `README.md`
3. this file
4. `docs/DESIGN_SYSTEM.md`
5. the component/template being changed

## Common Change Routes

| Request | Primary files |
| --- | --- |
| Change header size/layout | `template-parts/site-header.php`, `assets/css/main.css` |
| Change mobile menu | `template-parts/site-header.php`, `assets/js/site.js`, `assets/css/main.css` |
| Change hero pattern | `template-parts/page-hero.php`, `assets/css/main.css` |
| Change footer | `template-parts/site-footer.php`, `assets/css/main.css` |
| Change typography/colors/spacing | `assets/css/tokens.css`, `theme.json` |
| Change page shell | `page.php`, `front-page.php`, `single.php` |
| Preserve calculator/generator/chat | keep `the_content()` and do not edit shortcode owners |

## Preview And Staging Target

Preferred mechanism:

1. Create a separate Hostido staging WordPress install or staging subdomain.
2. Copy production database/media into staging.
3. Deploy this theme directory to staging `wp-content/themes/topinstal-theme`.
4. Activate only on staging.
5. Keep Elementor and functional plugins active while migrating pages.
6. Run browser QA and operator review.
7. Cut over only after a backup and rollback package exist.

Production preview by activating the theme on live is not acceptable.

## Deploy Sketch

Agent-executable deployment should be artifact based:

```text
clean Git state
-> build/package exact theme directory
-> SSH backup target theme directory
-> rsync/scp package to staging or production target
-> wp theme list / wp theme activate only when the target is correct
-> wp cache flush and LiteSpeed purge if needed
-> Playwright QA
-> rollback to backup on failure
```

No deployment command is encoded here yet because staging has not been provisioned.

