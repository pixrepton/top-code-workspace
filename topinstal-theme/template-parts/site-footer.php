<?php
/**
 * Site footer component.
 *
 * @package TopInstalTheme
 */

?>
<footer class="site-footer">
	<div class="container site-footer__grid">
		<div class="site-footer__brand">
			<p class="eyebrow"><?php esc_html_e( 'TOP-INSTAL', 'topinstal-theme' ); ?></p>
			<p class="site-footer__company"><?php echo esc_html( topinstal_theme_company() ); ?></p>
			<p><?php esc_html_e( 'Pompy ciepla, klimatyzacja i instalacje projektowane z naciskiem na poprawny dobor oraz montaz.', 'topinstal-theme' ); ?></p>
		</div>
		<nav class="site-footer__nav" aria-label="<?php esc_attr_e( 'Footer navigation', 'topinstal-theme' ); ?>">
			<?php
			wp_nav_menu( array(
				'theme_location' => 'footer',
				'container'      => false,
				'fallback_cb'    => false,
				'depth'          => 1,
			) );
			?>
		</nav>
		<div class="site-footer__contact">
			<a href="<?php echo esc_url( topinstal_theme_phone_href() ); ?>"><?php echo esc_html( topinstal_theme_phone() ); ?></a>
			<a href="<?php echo esc_url( 'mailto:' . topinstal_theme_email() ); ?>"><?php echo esc_html( topinstal_theme_email() ); ?></a>
		</div>
	</div>
	<div class="container site-footer__bottom">
		<p>&copy; <?php echo esc_html( gmdate( 'Y' ) ); ?> <?php echo esc_html( topinstal_theme_company() ); ?></p>
	</div>
</footer>

