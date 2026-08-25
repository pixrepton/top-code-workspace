<?php
/**
 * Theme setup and asset registration.
 *
 * @package TopInstalTheme
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

add_action( 'after_setup_theme', 'topinstal_theme_setup' );
function topinstal_theme_setup(): void {
	load_theme_textdomain( 'topinstal-theme', TOPINSTAL_THEME_PATH . '/languages' );

	add_theme_support( 'title-tag' );
	add_theme_support( 'post-thumbnails' );
	add_theme_support( 'custom-logo', array(
		'height'      => 80,
		'width'       => 260,
		'flex-height' => true,
		'flex-width'  => true,
	) );
	add_theme_support( 'html5', array( 'search-form', 'comment-form', 'comment-list', 'gallery', 'caption', 'style', 'script' ) );
	add_theme_support( 'responsive-embeds' );

	register_nav_menus( array(
		'primary' => __( 'Primary navigation', 'topinstal-theme' ),
		'footer'  => __( 'Footer navigation', 'topinstal-theme' ),
	) );
}

add_action( 'wp_enqueue_scripts', 'topinstal_theme_enqueue_assets' );
function topinstal_theme_enqueue_assets(): void {
	wp_enqueue_style(
		'topinstal-theme-tokens',
		TOPINSTAL_THEME_URI . '/assets/css/tokens.css',
		array(),
		TOPINSTAL_THEME_VERSION
	);

	wp_enqueue_style(
		'topinstal-theme-main',
		TOPINSTAL_THEME_URI . '/assets/css/main.css',
		array( 'topinstal-theme-tokens' ),
		TOPINSTAL_THEME_VERSION
	);

	wp_enqueue_script(
		'topinstal-theme-site',
		TOPINSTAL_THEME_URI . '/assets/js/site.js',
		array(),
		TOPINSTAL_THEME_VERSION,
		true
	);
}

add_action( 'customize_register', 'topinstal_theme_customize_register' );
function topinstal_theme_customize_register( WP_Customize_Manager $wp_customize ): void {
	$wp_customize->add_section( 'topinstal_contact', array(
		'title'    => __( 'TOP-INSTAL contact', 'topinstal-theme' ),
		'priority' => 35,
	) );

	$settings = array(
		'topinstal_phone'       => '+48 513 560 192',
		'topinstal_email'       => 'biuro.topinstal@gmail.com',
		'topinstal_company'     => 'TOP-INSTAL INNOVATIONS Sp. z o.o.',
		'topinstal_cta_label'   => 'Wycena online',
		'topinstal_cta_url'     => '/kalkulator/',
		'topinstal_facebook_url' => 'https://www.facebook.com/top.instal.klimatyzacja',
	);

	foreach ( $settings as $setting => $default ) {
		$wp_customize->add_setting( $setting, array(
			'default'           => $default,
			'sanitize_callback' => 'sanitize_text_field',
		) );

		$wp_customize->add_control( $setting, array(
			'label'   => ucwords( str_replace( array( 'topinstal_', '_' ), array( '', ' ' ), $setting ) ),
			'section' => 'topinstal_contact',
			'type'    => 'text',
		) );
	}
}

