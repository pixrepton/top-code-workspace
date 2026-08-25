<?php
/**
 * Single post template.
 *
 * @package TopInstalTheme
 */

get_header();
?>

<?php
while ( have_posts() ) :
	the_post();
	?>
	<article <?php post_class( 'article-shell' ); ?>>
		<header class="article-hero">
			<div class="container article-hero__inner">
				<p class="eyebrow"><?php esc_html_e( 'Baza wiedzy', 'topinstal-theme' ); ?></p>
				<h1><?php the_title(); ?></h1>
				<p class="article-meta"><?php echo esc_html( get_the_date() ); ?></p>
			</div>
		</header>
		<div class="section">
			<div class="container article-content content-flow">
				<?php the_content(); ?>
			</div>
		</div>
	</article>
	<?php
endwhile;

get_footer();

