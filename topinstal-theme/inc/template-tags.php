<?php
/**
 * Presentation helpers.
 *
 * @package TopInstalTheme
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

function topinstal_theme_mod( string $name, string $default = '' ): string {
	$value = get_theme_mod( $name, $default );
	return is_string( $value ) ? $value : $default;
}

function topinstal_theme_phone(): string {
	return topinstal_theme_mod( 'topinstal_phone', '+48 513 560 192' );
}

function topinstal_theme_phone_href(): string {
	return 'tel:' . preg_replace( '/[^0-9+]/', '', topinstal_theme_phone() );
}

function topinstal_theme_email(): string {
	return topinstal_theme_mod( 'topinstal_email', 'biuro.topinstal@gmail.com' );
}

function topinstal_theme_cta_label(): string {
	return topinstal_theme_mod( 'topinstal_cta_label', 'Wycena online' );
}

function topinstal_theme_cta_url(): string {
	return topinstal_theme_mod( 'topinstal_cta_url', '/kalkulator/' );
}

function topinstal_theme_company(): string {
	return topinstal_theme_mod( 'topinstal_company', 'TOP-INSTAL INNOVATIONS Sp. z o.o.' );
}

function topinstal_theme_excerpt_or_trimmed_content( int $words = 30 ): string {
	if ( has_excerpt() ) {
		return get_the_excerpt();
	}

	return wp_trim_words( wp_strip_all_tags( get_the_content() ), $words );
}

function topinstal_theme_has_builder_content(): bool {
	return 'builder' === get_post_meta( get_the_ID(), '_elementor_edit_mode', true );
}

function topinstal_theme_primary_menu_fallback(): void {
	?>
	<ul id="primary-menu" class="menu">
		<li><a href="<?php echo esc_url( home_url( '/' ) ); ?>"><?php esc_html_e( 'Home', 'topinstal-theme' ); ?></a></li>
		<li><a href="<?php echo esc_url( home_url( '/kalkulator/' ) ); ?>"><?php esc_html_e( 'Wycena online', 'topinstal-theme' ); ?></a></li>
		<li><a href="<?php echo esc_url( home_url( '/baza-wiedzy/' ) ); ?>"><?php esc_html_e( 'Baza wiedzy', 'topinstal-theme' ); ?></a></li>
		<li><a href="<?php echo esc_url( home_url( '/#kontakt' ) ); ?>"><?php esc_html_e( 'Kontakt', 'topinstal-theme' ); ?></a></li>
	</ul>
	<?php
}
