<?php
/**
 * TOP-INSTAL Theme bootstrap.
 *
 * @package TopInstalTheme
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

define( 'TOPINSTAL_THEME_VERSION', '0.1.0' );
define( 'TOPINSTAL_THEME_PATH', get_template_directory() );
define( 'TOPINSTAL_THEME_URI', get_template_directory_uri() );

require TOPINSTAL_THEME_PATH . '/inc/setup.php';
require TOPINSTAL_THEME_PATH . '/inc/template-tags.php';

