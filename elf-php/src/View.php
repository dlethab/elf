<?php
declare(strict_types=1);

namespace Elf;

use Elf\Services\Specs;
use Twig\Environment;
use Twig\Loader\FilesystemLoader;
use Twig\Markup;
use Twig\TwigFilter;
use Twig\TwigFunction;
use Twig\TwigTest;

/**
 * The Twig environment: the same helpers the Python edition gives its Jinja templates (_, csrf_token, fdate,
 * record_url, …), plus a few filters with Jinja's behaviour (tojson, truncate, urlencode, int).
 * Per-request values (current_user, lang, request, g) are globals too, so imported macros can use them.
 */
final class View
{
    public static function environment(App $app): Environment
    {
        $dev = in_array($app->config['ENV'], ['development', 'testing'], true);
        $cache = $dev ? false : Config::path((string) $app->config['TEMPLATE_CACHE']);
        $twig = new Environment(new FilesystemLoader(Config::root() . '/templates'), [
            'autoescape' => 'html', 'strict_variables' => false, 'cache' => $cache, 'auto_reload' => true,
        ]);
        // _('{n} records', n=5); or with a hash, for names Twig cannot take as arguments: _('… {from} …', {from: 1960})
        $_ = fn (?string $text = null, array $kw = []) => I18n::gettext($text,
            (count($kw) === 1 && isset($kw[0]) && is_array($kw[0])) ? $kw[0] : $kw);
        $fns = [
            '_' => [$_, ['is_variadic' => true]],
            'csrf_token' => [fn () => Security::csrfToken($app), []],
            'fdate' => [fn ($s = null, $e = null, $p = 'unknown') => I18n::fdate($s, $e, $p ?? 'unknown'), []],
            'precision_note' => [fn ($p) => I18n::precisionNote($p), []],
            'record_url' => [fn ($k, $s) => Queries::recordUrl((string) $k, (string) $s), []],
            'media_url' => [fn ($k) => Queries::mediaUrl((string) $k), []],
            'status_label' => [fn ($s) => isset(Vocab::STATUS_LABELS[$s]) ? [$_(Vocab::STATUS_LABELS[$s][0]), Vocab::STATUS_LABELS[$s][1]] : [$s, '•'], []],
            'kind_label' => [fn ($k) => $_(Vocab::KIND_LABELS[$k] ?? $k), []],
            'rights_label' => [fn ($r) => $_(Vocab::RIGHTS_LABELS[$r] ?? $r), []],
            'item_type_label' => [fn ($t) => $_(Vocab::ITEM_TYPE_LABELS[$t] ?? $t), []],
            'page_url' => [fn ($n) => $app->pageUrl((int) $n), []],
            'can' => [fn ($perm) => (bool) ($app->user && $app->user->can($perm)), []],
            'url_for' => [fn (string $name, array $kw = []) => $app->url($name, $kw), ['is_variadic' => true]],
            'get_flashed_messages' => [fn () => $app->takeFlashes(), []],
            'py' => [fn ($v) => self::py($v), []],
            // the explore page's no-JavaScript links: the current state with some values changed (set by the view)
            'nojs' => [fn (array $kw = []) => ($app->g['nojs'])($kw), ['is_variadic' => true]],
            // forum posts: the body is escaped and only paragraphs, line breaks and safe links are added
            'render' => [fn ($body) => Services\Forum::render($body), ['is_safe' => ['html']]],
            'can_edit' => [fn ($post, $user) => Services\Forum::canEdit((array) $post, $user), []],
            'display_name' => [fn ($row) => Services\Forum::displayName((array) $row), []],
        ];
        foreach ($fns as $name => [$fn, $opts]) {
            $twig->addFunction(new TwigFunction($name, $fn, $opts));
        }
        $safe = ['is_safe' => ['html']];
        $twig->addFilter(new TwigFilter('tojson', fn ($v) => self::tojson($v), $safe));
        $twig->addFilter(new TwigFilter('truncate', fn ($s, int $length = 255, bool $killwords = false, string $end = '...', int $leeway = 5)
            => self::truncate((string) $s, $length, $killwords, $end, $leeway)));
        $twig->addFilter(new TwigFilter('urlencode', fn ($s) => str_replace('%2F', '/', rawurlencode((string) $s))));
        $twig->addFilter(new TwigFilter('int', fn ($v, int $default = 0) => is_numeric($v) ? (int) $v : $default));
        $twig->addFilter(new TwigFilter('string', fn ($v) => self::py($v)));
        $twig->addFilter(new TwigFilter('py', fn ($v) => self::py($v)));
        $twig->addFilter(new TwigFilter('max', fn ($v) => $v ? max(is_array($v) ? $v : iterator_to_array($v)) : null));
        $twig->addFilter(new TwigFilter('min', fn ($v) => $v ? min(is_array($v) ? $v : iterator_to_array($v)) : null));
        $twig->addFilter(new TwigFilter('sum', fn ($v) => array_sum(is_array($v) ? $v : iterator_to_array($v))));
        $twig->addFilter(new TwigFilter('markup', fn ($s) => new Markup((string) $s, 'UTF-8')));
        $globals = [
            'ITEM_TYPES' => array_keys(Vocab::ITEM_TYPE_LABELS), 'CONSENT_LABELS' => Specs::CONSENT_LABELS,
            'EVIDENCE' => Vocab::EVIDENCE, 'languages' => I18n::LANGUAGES,
            'site_name' => $app->config['SITE_NAME'], 'contact_email' => $app->config['CONTACT_EMAIL'],
            'base_url' => $app->config['BASE_URL'], 'is_dev' => $dev, 'config' => $app->config,
            'request' => new RequestView($app), 'g' => new GView($app),
            // set for each page in context()
            'current_user' => null, 'unread_notifications' => 0, 'lang' => 'en', 'lang_dir' => 'ltr',
            'english_only' => false, 'translation_draft' => false,
        ];
        foreach ($globals as $k => $v) {
            $twig->addGlobal($k, $v);
        }
        return $twig;
    }

    /** The per-page values (Flask's context processor), set as globals so macros see them as Jinja's do. */
    public static function context(App $app, array $context): array
    {
        $lang = I18n::$current;
        $vals = [
            'current_user' => $app->user, 'unread_notifications' => $app->unreadNotifications(),
            'lang' => $lang, 'lang_dir' => I18n::LANGUAGES[$lang]['dir'],
            'english_only' => I18n::isEnglishOnly($app->req?->endpoint, $app->req?->viewArgs ?? []),
            'translation_draft' => $lang !== I18n::DEFAULT && I18n::isDraft($lang),
        ];
        foreach ($vals as $k => $v) {
            $app->twig->addGlobal($k, $v);
        }
        return $context;
    }

    /** Flask's tojson: JSON safe to put in a <script> or an attribute in single quotes. Keys sorted, as Flask does. */
    public static function tojson(mixed $v): string
    {
        $v = self::sortKeys($v);
        // < > & ' become < > & ', as in Flask
        // and, as Python's json.dumps, every non-ASCII character as \uXXXX
        $json = (string) json_encode($v, JSON_UNESCAPED_SLASHES | JSON_PRESERVE_ZERO_FRACTION
            | JSON_INVALID_UTF8_SUBSTITUTE | JSON_HEX_TAG | JSON_HEX_AMP | JSON_HEX_APOS);
        $u = '\\' . 'u00';
        $json = str_replace([$u . '3C', $u . '3E'], [$u . '3c', $u . '3e'], $json);
        // Python's separators (", " and ": "), so the page is the same as the Python edition's
        return (string) preg_replace_callback('/"(?:\\\\.|[^"\\\\])*"|[,:]/', fn ($m) => $m[0] === ',' ? ', ' : ($m[0] === ':' ? ': ' : $m[0]), $json);
    }

    private static function sortKeys(mixed $v): mixed
    {
        if ($v instanceof \JsonSerializable) {
            $v = $v->jsonSerialize();
        }
        if ($v instanceof \stdClass) {
            $v = (array) $v;
            if (!$v) {
                return new \stdClass();
            }
        }
        if (is_array($v)) {
            if (!array_is_list($v)) {
                ksort($v, SORT_STRING);
            }
            return array_map([self::class, 'sortKeys'], $v);
        }
        return $v;
    }

    /** Jinja's truncate: cut at a word boundary unless killwords, and only if longer than length + leeway. */
    public static function truncate(string $s, int $length = 255, bool $killwords = false, string $end = '...', int $leeway = 5): string
    {
        if (mb_strlen($s) <= $length + $leeway) {
            return $s;
        }
        if ($killwords) {
            return mb_substr($s, 0, $length - mb_strlen($end)) . $end;
        }
        $cut = mb_substr($s, 0, $length - mb_strlen($end));
        $pos = mb_strrpos($cut, ' ');
        $result = $pos === false ? $cut : mb_substr($cut, 0, $pos);
        return $result . $end;
    }

    /** A value printed as Python prints it (12.0 stays 12.0; True/False/None). */
    public static function py(mixed $v): string
    {
        return match (true) {
            is_float($v) => Services\Records::floatRepr($v),
            $v === true => 'True', $v === false => 'False', $v === null => 'None',
            default => (string) $v,
        };
    }
}
