#!/usr/bin/env bash
set -euo pipefail

url="${TOPINSTAL_PREVIEW_URL:-http://localhost:8097}"

if ! wp core is-installed --path=/var/www/html >/dev/null 2>&1; then
  wp core install \
    --url="$url" \
    --title="TOP-INSTAL Theme Preview" \
    --admin_user=admin \
    --admin_password=admin1234567890 \
    --admin_email=admin@example.test \
    --skip-email \
    --path=/var/www/html
fi

wp theme activate topinstal-theme --path=/var/www/html

page_ids="$(wp post list --post_type=page --format=ids --path=/var/www/html || true)"
if [ -n "$page_ids" ]; then
  wp post delete $page_ids --force --path=/var/www/html
fi

menu_names="$(wp menu list --format=csv --fields=name --path=/var/www/html | tail -n +2 || true)"
if [ -n "$menu_names" ]; then
  while IFS= read -r menu_name; do
    [ -n "$menu_name" ] && wp menu delete "$menu_name" --path=/var/www/html || true
  done <<EOF
$menu_names
EOF
fi

home_id="$(wp post create \
  --post_type=page \
  --post_status=publish \
  --post_title='Pompy ciepła i instalacje TOP-INSTAL' \
  --post_excerpt='Preview CMS lead. To pole jest zarządzane w WordPressie, a theme renderuje je jako lead hero.' \
  --post_content='<p>Preview CMS content. Ta strona sprawdza, czy theme renderuje treść z WordPressa i zostawia miejsce dla widgetów funkcyjnych.</p><h2>Wycena online</h2><p>[topinstal_lead_widget]</p><h2>Kontakt</h2><p>Telefon i CTA są renderowane przez theme, a treść pozostaje w CMS.</p>' \
  --porcelain \
  --path=/var/www/html)"

calc_id="$(wp post create \
  --post_type=page \
  --post_status=publish \
  --post_name=kalkulator \
  --post_title='Profesjonalny dobór pompy ciepła' \
  --post_content='<p>[heatpump_calc]</p>' \
  --porcelain \
  --path=/var/www/html)"

pdf_id="$(wp post create \
  --post_type=page \
  --post_status=publish \
  --post_name=pdf \
  --post_title='Generator oferty PDF' \
  --post_content='<p>[top_instal_offer_generator]</p>' \
  --porcelain \
  --path=/var/www/html)"

wp option update show_on_front page --path=/var/www/html
wp option update page_on_front "$home_id" --path=/var/www/html
wp option update permalink_structure '/%postname%/' --path=/var/www/html
wp rewrite flush --hard --path=/var/www/html

menu_id="$(wp menu create 'Preview primary' --porcelain --path=/var/www/html)"
wp menu item add-post "$menu_id" "$home_id" --title='Home' --path=/var/www/html
wp menu item add-post "$menu_id" "$calc_id" --title='Wycena online' --path=/var/www/html
wp menu item add-post "$menu_id" "$pdf_id" --title='PDF' --path=/var/www/html
wp menu item add-custom "$menu_id" 'Kontakt' "$url/#kontakt" --path=/var/www/html
wp menu location assign "$menu_id" primary --path=/var/www/html

wp theme mod set topinstal_phone '+48 513 560 192' --path=/var/www/html
wp theme mod set topinstal_email 'biuro.topinstal@gmail.com' --path=/var/www/html
wp theme mod set topinstal_cta_label 'Wycena online' --path=/var/www/html
wp theme mod set topinstal_cta_url '/kalkulator/' --path=/var/www/html

wp option get stylesheet --path=/var/www/html
wp option get template --path=/var/www/html
