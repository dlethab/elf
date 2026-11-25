<?php
declare(strict_types=1);

namespace Elf\Http;

/** One HTTP request: from PHP's globals in production, or built directly by the tests. */
final class Request
{
    public string $endpoint = '';
    public array $viewArgs = [];
    /** @var array<string, string[]> every value of each form field, in order (request.form.getlist) */
    public array $formLists = [];

    /**
     * @param array<string,string> $query
     * @param array<string,mixed> $form
     * @param array<string,array{path:string,name:string,size:int,error:int}> $files
     * @param array<string,string> $headers lower-case names
     */
    public function __construct(
        public readonly string $method,
        public readonly string $path,
        public readonly array $query = [],
        public readonly array $form = [],
        public readonly array $files = [],
        public readonly array $headers = [],
        public readonly array $cookies = [],
        public readonly string $remoteAddr = '127.0.0.1',
        public readonly string $scheme = 'http',
        public readonly string $host = 'localhost',
        public readonly string $rawQuery = '',
        public readonly int $contentLength = 0,
    ) {
    }

    public static function fromGlobals(int $trustedProxies = 0): self
    {
        $uri = $_SERVER['REQUEST_URI'] ?? '/';
        $path = rawurldecode(parse_url($uri, PHP_URL_PATH) ?: '/');
        $headers = [];
        foreach ($_SERVER as $k => $v) {
            if (str_starts_with($k, 'HTTP_')) {
                $headers[strtolower(str_replace('_', '-', substr($k, 5)))] = (string) $v;
            } elseif (in_array($k, ['CONTENT_TYPE', 'CONTENT_LENGTH'], true)) {
                $headers[strtolower(str_replace('_', '-', $k))] = (string) $v;
            }
        }
        $files = [];
        foreach ($_FILES as $name => $f) {
            if (is_array($f['tmp_name'] ?? null)) {
                continue;                           // multiple files under one name are not used by any form
            }
            $files[$name] = ['path' => (string) ($f['tmp_name'] ?? ''), 'name' => (string) ($f['name'] ?? ''),
                'size' => (int) ($f['size'] ?? 0), 'error' => (int) ($f['error'] ?? UPLOAD_ERR_NO_FILE)];
        }
        $remote = (string) ($_SERVER['REMOTE_ADDR'] ?? '?');
        $scheme = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off') ? 'https' : 'http';
        $host = (string) ($_SERVER['HTTP_HOST'] ?? 'localhost');
        if ($trustedProxies > 0) {
            // Behind a proxy or CDN: take the visitor's address and scheme from the proxy's headers, trusting only as
            // many hops as configured, so rate limits and lockouts apply per visitor, not to the proxy.
            $fwd = array_map('trim', explode(',', $headers['x-forwarded-for'] ?? ''));
            if (count($fwd) >= $trustedProxies && $fwd[count($fwd) - $trustedProxies] !== '') {
                $remote = $fwd[count($fwd) - $trustedProxies];
            }
            $protos = array_map('trim', explode(',', $headers['x-forwarded-proto'] ?? ''));
            if (count($protos) >= $trustedProxies && $protos[count($protos) - $trustedProxies] !== '') {
                $scheme = $protos[count($protos) - $trustedProxies];
            }
            $hosts = array_map('trim', explode(',', $headers['x-forwarded-host'] ?? ''));
            if (count($hosts) >= $trustedProxies && $hosts[count($hosts) - $trustedProxies] !== '') {
                $host = $hosts[count($hosts) - $trustedProxies];
            }
        }
        $rawQuery = (string) ($_SERVER['QUERY_STRING'] ?? '');
        [$query] = self::parseQs($rawQuery);
        $method = strtoupper((string) ($_SERVER['REQUEST_METHOD'] ?? 'GET'));
        $ctype = strtolower($headers['content-type'] ?? '');
        $lists = [];
        if (str_starts_with($ctype, 'application/x-www-form-urlencoded')) {
            // parsed here rather than from $_POST, so a repeated name keeps every value and the first wins for .get (as Flask),
            // and names with dots or spaces are kept as sent
            [$form, $lists] = self::parseQs((string) file_get_contents('php://input'));
        } else {
            $form = self::strings($_POST);
            foreach ($_POST as $k => $v) {
                if (is_array($v)) {
                    $lists[(string) $k] = array_values(array_filter($v, 'is_string'));
                } elseif (is_string($v)) {
                    $lists[(string) $k] = [$v];
                }
            }
        }
        $r = new self($method, $path, $query, $form, $files, $headers,
            self::strings($_COOKIE), $remote, $scheme, $host, $rawQuery, (int) ($_SERVER['CONTENT_LENGTH'] ?? 0));
        $r->formLists = $lists;
        return $r;
    }

    /** A query string or urlencoded body: [first value of each name, every value of each name]. */
    public static function parseQs(string $qs): array
    {
        $first = [];
        $lists = [];
        foreach (explode('&', $qs) as $pair) {
            if ($pair === '') {
                continue;
            }
            [$k, $v] = array_pad(explode('=', $pair, 2), 2, '');
            $k = urldecode($k);
            $v = urldecode($v);
            if (!mb_check_encoding($k, 'UTF-8') || !mb_check_encoding($v, 'UTF-8')) {
                $k = mb_scrub($k, 'UTF-8');
                $v = mb_scrub($v, 'UTF-8');
            }
            if (!array_key_exists($k, $first)) {
                $first[$k] = $v;
            }
            $lists[$k][] = $v;
        }
        return [$first, $lists];
    }

    /** request.form.getlist(k) */
    public function postList(string $k): array
    {
        return $this->formLists[$k] ?? (isset($this->form[$k]) ? [(string) $this->form[$k]] : []);
    }

    /** Form and query values as strings only (a field sent as name[]=… is ignored, as no form uses that). */
    private static function strings(array $a): array
    {
        $out = [];
        foreach ($a as $k => $v) {
            if (is_string($v)) {
                $out[(string) $k] = $v;
            }
        }
        return $out;
    }

    /** For tests: GET/POST a URL (with its query string) and form fields. */
    public static function create(string $method, string $uri, array $form = [], array $files = [], array $headers = [], array $cookies = [],
                                  string $remoteAddr = '127.0.0.1'): self
    {
        $path = rawurldecode(parse_url($uri, PHP_URL_PATH) ?: '/');
        $rawQuery = (string) (parse_url($uri, PHP_URL_QUERY) ?? '');
        [$query] = self::parseQs($rawQuery);
        $scalar = fn ($v) => is_bool($v) ? ($v ? '1' : '') : (string) $v;
        $lists = [];
        $first = [];
        foreach ($form as $k => $v) {              // a list value is a repeated field (sid=1&sid=2)
            $vals = is_array($v) ? array_map($scalar, array_values($v)) : [$scalar($v)];
            $lists[(string) $k] = $vals;
            if ($vals) {
                $first[(string) $k] = $vals[0];
            }
        }
        $r = new self(strtoupper($method), $path, $query, $first, $files, array_change_key_case($headers, CASE_LOWER), $cookies,
            $remoteAddr, 'http', 'localhost', $rawQuery);
        $r->formLists = $lists;
        return $r;
    }

    public function arg(string $k, ?string $default = null): ?string
    {
        return $this->query[$k] ?? $default;
    }

    public function argInt(string $k, int $default): int
    {
        $v = $this->query[$k] ?? null;
        return ($v !== null && preg_match('/^-?\d+$/', trim($v))) ? (int) $v : $default;
    }

    public function post(string $k, ?string $default = null): ?string
    {
        $v = $this->form[$k] ?? $default;
        return is_string($v) || $v === null ? $v : (string) $v;
    }

    /** request.values: query string and form together (form wins). */
    public function value(string $k, ?string $default = null): ?string
    {
        return $this->form[$k] ?? ($this->query[$k] ?? $default);
    }

    public function header(string $k, ?string $default = null): ?string
    {
        return $this->headers[strtolower($k)] ?? $default;
    }

    /** Path and query, always with "?" as Flask's request.full_path. */
    public function fullPath(): string
    {
        return $this->path . '?' . $this->rawQuery;
    }

    public function file(string $name): ?array
    {
        $f = $this->files[$name] ?? null;
        if (!$f || ($f['error'] ?? 0) !== UPLOAD_ERR_OK || !is_file($f['path'])) {
            return null;
        }
        return $f;
    }

    public function isUnsafe(): bool
    {
        return in_array($this->method, ['POST', 'PUT', 'PATCH', 'DELETE'], true);
    }
}
