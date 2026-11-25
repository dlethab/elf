<?php
declare(strict_types=1);

/*
 * The front controller: every request that is not a file in this folder comes here (see .htaccess).
 * Only this folder is published by the web server; the code, settings and database live one level up.
 *
 * Also the router script for PHP's built-in server:  php -S 127.0.0.1:8000 -t public public/index.php
 */

if (PHP_SAPI === 'cli-server') {
    $path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?: '/';
    // the built-in server serves static files itself; everything else, including /static/ addresses with ?v=, is handled
    // by the app so headers (caching, nosniff) are the same as in production
    if ($path !== '/' && $path !== '/index.php' && !str_starts_with($path, '/static/') && is_file(__DIR__ . $path)) {
        return false;
    }
}

// The project folder: normally one level up (…/elf-php/public/index.php). On hosting where the web folder is fixed
// (public_html), copy this folder's contents into public_html and upload the project next to it as "elf-php".
$root = dirname(__DIR__);
if (!is_file($root . '/vendor/autoload.php') && is_file(dirname(__DIR__) . '/elf-php/vendor/autoload.php')) {
    $root = dirname(__DIR__) . '/elf-php';
}
require $root . '/vendor/autoload.php';

try {
    $app = new Elf\App();
} catch (Throwable $e) {
    // a configuration error (for example a missing secret key in production): details go to the server log only
    error_log('[elf] Could not start: ' . $e->getMessage());
    http_response_code(500);
    header('Content-Type: text/plain; charset=utf-8');
    echo "The archive is not configured correctly. The administrator can find the reason in the server's error log.\n";
    exit;
}
if ($app->config['ENV'] === 'production') {
    ini_set('display_errors', '0');          // errors go to the server log, never into a page
}
$request = Elf\Http\Request::fromGlobals((int) $app->config['TRUSTED_PROXIES']);
$app->handle($request)->send();
