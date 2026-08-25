<?php
/**
 * Default index template.
 *
 * @package TopInstalTheme
 */

get_header();
?>

<section class="page-hero page-hero--compact">
	<div class="container page-hero__inner">
		<p class="eyebrow"><?php esc_html_e( 'TOP-INSTAL', 'topinstal-theme' ); ?></p>
		<h1><?php esc_html_e( 'Baza wiedzy', 'topinstal-theme' ); ?></h1>
	</div>
</section>

<section class="section">
	<div class="container post-grid">
		<?php
		if ( have_posts() ) :
			while ( have_posts() ) :
				the_post();
				get_template_part( 'template-parts/post-card' );
			endwhile;
		else :
			?>
			<p><?php esc_html_e( 'Brak wpisow do wyswietlenia.', 'topinstal-theme' ); ?></p>
			<?php
		endif;
		?>
	</div>
</section>

<?php
get_footer();

