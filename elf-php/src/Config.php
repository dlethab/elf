<?php
declare(strict_types=1);

namespace Elf;

/**
 * Settings, from environment variables or a `.env` file in the project folder (outside the public web folder),
 * which is how most shared hosting is configured. The same ELF_* names as the Python edition.
 */
final class Config
{
    public const DEV_SECRET = 'dev-only-insecure-secret-change-me';

    /** The project folder (one level above public/). Relative paths in settings are resolved against it. */
    public static function root(): string
    {
        return dirname(__DIR__);
    }

    /** Values from ROOT/.env (KEY=value lines; # comments; optional quotes). Real environment variables win. */
    public static function dotenv(?string $file = null): array
    {
        $file ??= self::root() . '/.env';
        $out = [];
        if (!is_file($file)) {
            return $out;
        }
        foreach (preg_split('/\R/', (string) file_get_contents($file)) as $line) {
            $line = trim($line);
            if ($line === '' || $line[0] === '#' || !str_contains($line, '=')) {
                continue;
            }
            [$k, $v] = array_map('trim', explode('=', $line, 2));
            if (str_starts_with($k, 'export ')) {
                $k = trim(substr($k, 7));
            }
            if (strlen($v) >= 2 && ($v[0] === '"' || $v[0] === "'") && $v[-1] === $v[0]) {
                $v = substr($v, 1, -1);
            } else {
                $v = trim(preg_replace('/\s+#.*$/', '', $v));
            }
            $out[$k] = $v;
        }
        return $out;
    }

    private static function env(array $file, string $name, ?string $default = null): ?string
    {
        $v = getenv($name);
        if ($v !== false) {
            return $v;
        }
        return $file[$name] ?? $default;
    }

    private static function bool(array $file, string $name, bool $default): bool
    {
        $v = self::env($file, $name);
        return $v === null ? $default : in_array(strtolower(trim($v)), ['1', 'true', 'yes', 'on'], true);
    }

    /** Validated origins ('https://host' or 'https://host:port', nothing else). http:// only outside production. */
    public static function origins(string|array $value, string $env): array
    {
        $items = is_array($value) ? $value : preg_split('/[\s,]+/', $value ?: '');
        $out = [];
        $re = $env === 'production' ? '~^https://[a-z0-9.-]+(:\d{1,5})?$~' : '~^https?://[a-z0-9.-]+(:\d{1,5})?$~';
        foreach ($items as $i) {
            $o = rtrim(trim((string) $i), '/');
            if ($o === '') {
                continue;
            }
            if (!preg_match($re, strtolower($o))) {
                throw new \RuntimeException("ELF_EMBED_ORIGINS: '{$o}' is not a site address like https://elfveterans.org");
            }
            $out[] = strtolower($o);
        }
        return $out;
    }

    public static function path(string $p): string
    {
        if ($p === ':memory:' || $p === '') {
            return $p;
        }
        $isAbs = str_starts_with($p, '/') || str_starts_with($p, '\\') || preg_match('~^[A-Za-z]:[\\\\/]~', $p);
        return $isAbs ? $p : self::root() . '/' . $p;
    }

    public static function load(array $overrides = [], ?array $file = null): array
    {
        $f = $file ?? self::dotenv();
        $env = $overrides['ENV'] ?? self::env($f, 'ELF_ENV', 'development');
        $mb = fn (string $n, int $d) => (int) self::env($f, $n, (string) $d);
        $cfg = [
            'ENV' => $env,
            'SECRET_KEY' => self::env($f, 'ELF_SECRET_KEY', self::DEV_SECRET),
            'DATABASE_PATH' => self::env($f, 'ELF_DATABASE_PATH', 'instance/archive.db'),
            'BASE_URL' => rtrim((string) self::env($f, 'ELF_BASE_URL', 'http://localhost:8000'), '/'),
            'SITE_NAME' => self::env($f, 'ELF_SITE_NAME', 'ELF Digital Historical Archive'),
            'CONTACT_EMAIL' => self::env($f, 'ELF_CONTACT_EMAIL', ''),
            'REQUIRE_EMAIL_VERIFICATION' => self::bool($f, 'ELF_REQUIRE_EMAIL_VERIFICATION', true),
            'ALLOW_SELF_REVIEW' => self::bool($f, 'ELF_ALLOW_SELF_REVIEW', false),
            // Staff (editors, moderators, researchers, administrators) must turn on two-step sign-in.
            'REQUIRE_STAFF_MFA' => self::bool($f, 'ELF_REQUIRE_STAFF_MFA', false),
            'SESSION_LIFETIME_SECONDS' => (int) self::env($f, 'ELF_SESSION_LIFETIME_SECONDS', (string) (7 * 24 * 3600)),
            'SMTP_HOST' => self::env($f, 'ELF_SMTP_HOST', ''),
            'SMTP_PORT' => (int) self::env($f, 'ELF_SMTP_PORT', '587'),
            'SMTP_USER' => self::env($f, 'ELF_SMTP_USER', ''),
            'SMTP_PASSWORD' => self::env($f, 'ELF_SMTP_PASSWORD', ''),
            'SMTP_FROM' => self::env($f, 'ELF_SMTP_FROM', ''),
            // On a development machine pending migrations are applied at start-up, so new code never meets an old
            // database. In production they are applied deliberately (`php bin/elf migrate`, after a backup).
            'AUTO_MIGRATE' => self::bool($f, 'ELF_AUTO_MIGRATE', $env === 'development'),
            // Number of reverse proxies in front of the app (1 behind a proxy or CDN). 0 = none.
            'TRUSTED_PROXIES' => (int) self::env($f, 'ELF_TRUSTED_PROXIES', '0'),
            // Uploaded files live OUTSIDE the public web folder and are only served through the access-checking /media route.
            'MEDIA_ROOT' => self::env($f, 'ELF_MEDIA_ROOT', 'instance/media'),
            // Optional street-level map layer. Empty = the archive's own base map only, with no third party involved.
            'MAP_TILE_URL' => self::env($f, 'ELF_MAP_TILE_URL', ''),
            'MAP_TILE_ATTRIBUTION' => self::env($f, 'ELF_MAP_TILE_ATTRIBUTION', ''),
            'MAX_PHOTO_BYTES' => $mb('ELF_MAX_PHOTO_MB', 15) * 1024 * 1024,
            'MAX_PHOTOS_PER_SUBMISSION' => $mb('ELF_MAX_PHOTOS_PER_SUBMISSION', 10),
            'MAX_DOCUMENT_BYTES' => $mb('ELF_MAX_DOCUMENT_MB', 30) * 1024 * 1024,
            'MAX_AV_BYTES' => $mb('ELF_MAX_AV_MB', 250) * 1024 * 1024,
            'MAX_CONTENT_LENGTH' => (max($mb('ELF_MAX_PHOTO_MB', 15), $mb('ELF_MAX_DOCUMENT_MB', 30), $mb('ELF_MAX_AV_MB', 250)) + 2) * 1024 * 1024,
            // Sites allowed to show the map and timeline in a frame (space- or comma-separated origins). Empty = none.
            'EMBED_ORIGINS' => self::env($f, 'ELF_EMBED_ORIGINS', ''),
            // Where Twig keeps compiled templates (production only; development recompiles on change).
            'TEMPLATE_CACHE' => self::env($f, 'ELF_TEMPLATE_CACHE', 'instance/cache/twig'),
        ];
        $cfg = array_merge($cfg, $overrides);
        $cfg['EMBED_ORIGINS'] = self::origins($cfg['EMBED_ORIGINS'], $cfg['ENV']);
        if ($cfg['ENV'] === 'production') {
            if ($cfg['SECRET_KEY'] === self::DEV_SECRET || strlen((string) $cfg['SECRET_KEY']) < 32) {
                throw new \RuntimeException('ELF_SECRET_KEY must be set to a random value of at least 32 characters in production.');
            }
            if (!str_starts_with((string) $cfg['BASE_URL'], 'https://')) {
                throw new \RuntimeException('ELF_BASE_URL must be an https:// URL in production.');
            }
        }
        return $cfg;
    }
}
