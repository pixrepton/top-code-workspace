<?php
/**
 * Post card component.
 *
 * @package TopInstalTheme
 */

?>
<article <?php post_class( 'post-card' ); ?>>
	<a class="post-card__link" href="<?php the_permalink(); ?>">
		<?php if ( has_post_thumbnail() ) : ?>
			<div class="post-card__media"><?php the_post_thumbnail( 'medium_large' ); ?></div>
		<?php endif; ?>
		<div class="post-card__body">
			<p class="post-card__date"><?php echo esc_html( get_the_date() ); ?></p>
			<h2><?php the_title(); ?></h2>
			<p><?php echo esc_html( topinstal_theme_excerpt_or_trimmed_content( 22 ) ); ?></p>
		</div>
	</a>
</article>

