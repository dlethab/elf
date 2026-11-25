<?php
declare(strict_types=1);

namespace Elf;

use Elf\Http\HttpException;
use Elf\Http\Redirect;
use Elf\Http\Request;
use Elf\Http\Response;

/** CSRF, security headers, safe redirects, caching policy, staff-route guards. */
final class Security
{
    /** blob: images: the map decodes its own elevation tiles in the browser (MapLibre's image fallback path) */
    public const CSP = "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; "
        . "frame-ancestors 'none'; form-action 'self'; base-uri 'none'; object-src 'none'";
    public const PRIVATE_PREFIXES = ['/dashboard', '/editor', '/admin', '/auth', '/dev', '/contribute', '/moderation'];
    /** The only pages another site may show in a frame: the public map and timeline, in their embedded layout (?embed=1). */
    public const EMBED_PATHS = ['/explore', '/map', '/timeline'];

    public static function csrfToken(App $app): string
    {
        if (!$app->session->has('csrf')) {
            $app->session->set('csrf', Services\Util::tokenUrlsafe(32));
        }
        return $app->session->get('csrf');
    }

    public static function checkCsrf(App $app, Request $req): void
    {
        if ($req->isUnsafe()) {
            $sent = (string) ($req->post('csrf_token') ?: ($req->header('X-CSRF-Token') ?: ''));
            $expected = (string) $app->session->get('csrf', '');
            if ($expected === '' || !hash_equals($expected, $sent)) {
                throw new HttpException(400, 'Your session expired or the form was invalid. Please go back, reload, and try again.');
            }
        }
    }

    /** Only same-site relative paths; blocks open redirects such as //evil.test or https://evil.test. */
    public static function safeNext(?string $target, string $default = '/'): string
    {
        if (!$target) {
            return $default;
        }
        $u = parse_url($target);
        if ($u === false || isset($u['scheme']) || isset($u['host']) || !str_starts_with($target, '/') || str_starts_with($target, '//')
            || str_contains($target, '\\')) {
            return $default;
        }
        return $target;
    }

    public static function loginRequired(App $app): void
    {
        if (!$app->user) {
            throw new Redirect($app->url('auth.login', ['next' => rtrim($app->req->fullPath(), '?')]));
        }
    }

    /** Server-side permission gate. Anonymous → sign-in; signed in without permission → 403. */
    public static function requirePerm(App $app, string $permission): void
    {
        if (!$app->user) {
            throw new Redirect($app->url('auth.login', ['next' => rtrim($app->req->fullPath(), '?')]));
        }
        if (!$app->user->can($permission)) {
            throw new HttpException(403);
        }
        // optional policy: staff must use two-step sign-in before using staff tools
        if (($app->config['REQUIRE_STAFF_MFA'] ?? false) && !in_array($permission, Permissions::CONTRIBUTOR, true) && !$app->user->mfa_enabled) {
            $app->flash('Your role requires two-step sign-in. Please turn it on to continue.', 'error');
            throw new Redirect($app->url('dashboard.security'));
        }
    }

    /** The policy above, plus the map tile host only if an administrator configured one. */
    public static function buildCsp(array $config): string
    {
        $tile = (string) ($config['MAP_TILE_URL'] ?? '');
        if ($tile === '') {
            return self::CSP;
        }
        $u = parse_url(str_replace(['{s}', '{z}', '{x}', '{y}', '{r}'], ['a', '0', '0', '0', ''], $tile));
        $host = '';
        if (($u['scheme'] ?? '') === 'https' && !empty($u['host'])) {
            $host = 'https://' . $u['host'] . (isset($u['port']) ? ':' . $u['port'] : '');
            $host = str_replace('://a.', '://*.', $host);
        }
        return $host ? str_replace("img-src 'self' data: blob:", "img-src 'self' data: blob: {$host}", self::CSP) : self::CSP;
    }

    private static function embeddable(App $app, Request $req): ?array
    {
        $origins = $app->config['EMBED_ORIGINS'] ?? [];
        $ok = $origins && $req->method === 'GET' && in_array($req->path, self::EMBED_PATHS, true) && $req->arg('embed') === '1';
        return $ok ? $origins : null;
    }

    private static function startsWithAny(string $path, array $prefixes): bool
    {
        foreach ($prefixes as $p) {
            if (str_starts_with($path, $p)) {
                return true;
            }
        }
        return false;
    }

    public static function applyHeaders(App $app, Request $req, Response $r): void
    {
        $r->set('Content-Security-Policy', $app->config['CSP'] ?? self::CSP);
        $r->set('X-Content-Type-Options', 'nosniff');
        $origins = self::embeddable($app, $req);
        if ($origins) {          // X-Frame-Options cannot name a site; frame-ancestors is the rule browsers apply here
            $r->set('Content-Security-Policy', str_replace("frame-ancestors 'none'", 'frame-ancestors ' . implode(' ', $origins), $r->get('Content-Security-Policy')));
        } else {
            $r->set('X-Frame-Options', 'DENY');
        }
        $r->set('Referrer-Policy', 'strict-origin-when-cross-origin');
        $r->set('Permissions-Policy', 'geolocation=(), camera=(), microphone=()');
        if (($app->config['ENV'] ?? '') === 'production') {       // production is https-only (enforced in Config)
            $r->set('Strict-Transport-Security', 'max-age=31536000; includeSubDomains');
        }
        $r->add('Vary', 'Cookie');
        // Anything personalised, or any non-GET, is never cacheable. Anonymous public GETs must revalidate,
        // so an unpublished record cannot linger in a shared cache.
        if ($app->user || $req->method !== 'GET' || self::startsWithAny($req->path, self::PRIVATE_PREFIXES)) {
            $r->set('Cache-Control', 'private, no-store');
        } elseif (str_starts_with($req->path, '/static/')) {
            if ($req->arg('v')) {                             // versioned by content date (see App::staticUrl)
                $r->set('Cache-Control', 'public, max-age=31536000, immutable');
            } elseif (str_starts_with($req->path, '/static/map/terrain/')) {
                $r->set('Cache-Control', 'public, max-age=2592000');   // elevation tiles change only when rebuilt
            } else {
                $r->set('Cache-Control', 'public, max-age=3600');
            }
        } elseif (!str_contains((string) $r->get('Cache-Control'), 'no-store')) {   // a view may make a response stricter, never looser
            $r->set('Cache-Control', 'public, max-age=0, must-revalidate');
        }
        if (self::startsWithAny($req->path, self::PRIVATE_PREFIXES)) {
            $r->set('X-Robots-Tag', 'noindex, nofollow');
        }
    }
}
