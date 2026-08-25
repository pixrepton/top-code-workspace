<?php
/**
 * Site header component.
 *
 * @package TopInstalTheme
 */

?>
<header class="site-header" data-site-header>
	<div class="container site-header__inner">
		<a class="brand" href="<?php echo esc_url( home_url( '/' ) ); ?>" aria-label="<?php esc_attr_e( 'TOP-INSTAL homepage', 'topinstal-theme' ); ?>">
			<?php if ( has_custom_logo() ) : ?>
				<?php the_custom_logo(); ?>
			<?php else : ?>
				<span class="brand__mark">TOP</span>
				<span class="brand__text">TOP-INSTAL</span>
			<?php endif; ?>
		</a>

		<button class="menu-toggle" type="button" aria-expanded="false" aria-controls="primary-menu" data-menu-toggle>
			<span class="menu-toggle__bar"></span>
			<span class="screen-reader-text"><?php esc_html_e( 'Toggle navigation', 'topinstal-theme' ); ?></span>
		</button>

		<nav class="primary-nav" aria-label="<?php esc_attr_e( 'Primary navigation', 'topinstal-theme' ); ?>" data-primary-nav>
			<?php
			wp_nav_menu( array(
				'theme_location' => 'primary',
				'menu_id'        => 'primary-menu',
				'container'      => false,
				'fallback_cb'    => 'topinstal_theme_primary_menu_fallback',
			) );
			?>
		</nav>

		<div class="header-actions">
			<a class="header-phone" href="<?php echo esc_url( topinstal_theme_phone_href() ); ?>"><?php echo esc_html( topinstal_theme_phone() ); ?></a>
			<a class="button button--primary" href="<?php echo esc_url( topinstal_theme_cta_url() ); ?>"><?php echo esc_html( topinstal_theme_cta_label() ); ?></a>
		</div>
	</div>
</header>
