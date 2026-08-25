<?php
/**
 * Front page template.
 *
 * @package TopInstalTheme
 */

get_header();
?>

<?php
while ( have_posts() ) :
	the_post();
	get_template_part( 'template-parts/page-hero' );
	?>
	<section class="section section--content">
		<div class="container content-flow">
			<?php the_content(); ?>
		</div>
	</section>
	<?php
endwhile;

get_footer();

