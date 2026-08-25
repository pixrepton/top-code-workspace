<?php
/**
 * Page hero component.
 *
 * @package TopInstalTheme
 */

$is_builder_page = topinstal_theme_has_builder_content();
?>
<section class="page-hero<?php echo $is_builder_page ? ' page-hero--builder-aware' : ''; ?>">
	<div class="container page-hero__inner">
		<div class="page-hero__copy">
			<p class="eyebrow"><?php esc_html_e( 'TOP-INSTAL', 'topinstal-theme' ); ?></p>
			<h1><?php the_title(); ?></h1>
			<?php if ( ! $is_builder_page ) : ?>
				<p class="page-hero__lead"><?php echo esc_html( topinstal_theme_excerpt_or_trimmed_content( 28 ) ); ?></p>
			<?php endif; ?>
			<div class="page-hero__actions">
				<a class="button button--primary" href="<?php echo esc_url( topinstal_theme_cta_url() ); ?>"><?php echo esc_html( topinstal_theme_cta_label() ); ?></a>
				<a class="button button--ghost" href="<?php echo esc_url( topinstal_theme_phone_href() ); ?>"><?php echo esc_html( topinstal_theme_phone() ); ?></a>
			</div>
		</div>
		<?php if ( has_post_thumbnail() ) : ?>
			<div class="page-hero__media">
				<?php the_post_thumbnail( 'large' ); ?>
			</div>
		<?php endif; ?>
	</div>
</section>

