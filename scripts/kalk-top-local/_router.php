<?php
$path = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);
$full = __DIR__ . $path;
if ($path !== '/' && file_exists($full) && !is_dir($full)) { return false; }
if (strpos($path, '/wp-json/') === 0) {
    $_GET['rest_route'] = '/' . ltrim(substr($path, 8), '/');
    $_SERVER['PATH_INFO'] = '/' . ltrim(substr($path, 8), '/');
}
require __DIR__ . '/index.php';
