<?php
declare(strict_types=1);

namespace Elf;

use Elf\Services\Dates;

/**
 * Interface languages: English (source), Tigrinya and Arabic (right-to-left).
 *
 * Only INTERFACE text is translated. Historical content (names, biographies, captions, sources) is always shown
 * exactly as it was recorded, in whatever language and script it was entered.
 *
 * The Tigrinya and Arabic catalogues in translations/*.json are DRAFTS until reviewed by native speakers; the site says
 * so on every translated page. A missing translation falls back to English, so an incomplete catalogue never breaks a
 * page. Strings are looked up by their English text; placeholders use {name}: _('{n} published records', n=5).
 * The catalogues are the Python edition's, unchanged.
 */
final class I18n
{
    public const LANGUAGES = [
        'en' => ['name' => 'English', 'dir' => 'ltr'],
        'ti' => ['name' => 'ትግርኛ', 'dir' => 'ltr'],
        'ar' => ['name' => 'العربية', 'dir' => 'rtl'],
    ];
    public const DEFAULT = 'en';
    public const COOKIE = 'elf_lang';
    /** Pages that are still English-only (route names). They are marked lang="en" so screen readers pronounce them correctly. */
    public const ENGLISH_ONLY_PREFIXES = ['editor.', 'admin.', 'dev.', 'community.mod'];
    /** Legal drafts are translated only after a lawyer has approved the English text. */
    public const ENGLISH_ONLY_PAGES = ['privacy', 'terms', 'copyright', 'data-policy'];

    private static array $catalogs = [];
    public static array $reviewed = [];
    public static string $current = self::DEFAULT;

    public static function catalogDir(): string
    {
        return Config::root() . '/translations';
    }

    public static function &catalog(string $lang): array
    {
        if (!isset(self::$catalogs[$lang])) {
            $path = self::catalogDir() . "/{$lang}.json";
            $data = is_file($path) ? (json_decode((string) file_get_contents($path), true) ?: []) : [];
            $meta = $data['_meta'] ?? [];
            unset($data['_meta']);
            self::$reviewed[$lang] = ($meta['status'] ?? null) === 'reviewed';
            self::$catalogs[$lang] = $data;
        }
        return self::$catalogs[$lang];
    }

    /** True until a native-speaker review is recorded by setting "_meta": {"status": "reviewed"} in the catalogue. */
    public static function isDraft(string $lang): bool
    {
        self::catalog($lang);
        return !(self::$reviewed[$lang] ?? false);
    }

    /** Python's str.format with names only; a missing placeholder raises, so the caller can fall back to English. */
    public static function format(string $s, array $kw): string
    {
        $out = preg_replace_callback('/\{\{|\}\}|\{(\w*)\}/', function ($m) use ($kw) {
            if ($m[0] === '{{') {
                return '{';
            }
            if ($m[0] === '}}') {
                return '}';
            }
            if (!array_key_exists($m[1], $kw)) {
                throw new \OutOfBoundsException($m[1]);
            }
            $v = $kw[$m[1]];
            return is_bool($v) ? ($v ? 'True' : 'False') : (is_float($v) ? Services\Records::floatRepr($v) : (string) $v);
        }, $s);
        return (string) $out;
    }

    public static function gettext(?string $text, array $kw = []): ?string
    {
        if ($text === null || $text === '') {
            return $text;
        }
        $lang = self::$current;
        $out = ($lang !== self::DEFAULT ? (self::catalog($lang)[$text] ?? null) : null) ?: $text;
        if ($kw) {
            try {
                return self::format($out, $kw);
            } catch (\OutOfBoundsException) {
                return self::format($text, $kw);     // a broken translation never breaks the page
            }
        }
        return $out;
    }

    public static function fdate(?string $start, ?string $end = null, ?string $precision = 'unknown'): string
    {
        return Dates::format($start, $end, $precision, array_map(fn ($m) => self::gettext($m), Dates::MONTHS),
            self::gettext('c.'), self::gettext('Unknown'));
    }

    public static function precisionNote(?string $precision): string
    {
        return (string) self::gettext(Dates::precisionNote($precision));
    }

    public static function isEnglishOnly(?string $endpoint, array $viewArgs = []): bool
    {
        if ($endpoint === 'public.info') {
            return in_array($viewArgs['page'] ?? null, self::ENGLISH_ONLY_PAGES, true);
        }
        if (!$endpoint) {
            return false;
        }
        foreach (self::ENGLISH_ONLY_PREFIXES as $p) {
            if (str_starts_with($endpoint, $p)) {
                return true;
            }
        }
        return false;
    }
}
