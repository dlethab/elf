<?php
declare(strict_types=1);

namespace Elf\Http;

/**
 * Routes in the Python edition's notation: /people/<slug>, /submissions/<int:sid>, /contribute/<any(a,b):kind>.
 * Each route has a name ("blueprint.view", as in Flask) used to build addresses and to decide which pages are
 * English-only.
 */
final class Router
{
    /** @var array<int, array{methods:string[], pattern:string, regex:string, params:array, handler:callable, name:string}> */
    private array $routes = [];
    /** @var array<string, int> */
    private array $byName = [];

    public function add(string $methods, string $pattern, callable $handler, string $name): void
    {
        $params = [];
        $regex = preg_replace_callback('/<(?:(\w+)(?:\(([^)]*)\))?:)?(\w+)>/', function ($m) use (&$params) {
            $conv = $m[1] ?: 'string';
            $name = $m[3];
            $params[$name] = $conv;
            return match ($conv) {
                'int' => "(?P<{$name}>\\d+)",
                'path' => "(?P<{$name}>.+)",
                'any' => '(?P<' . $name . '>' . implode('|', array_map(fn ($s) => preg_quote(trim($s), '~'), explode(',', $m[2]))) . ')',
                default => "(?P<{$name}>[^/]+)",
            };
        }, $pattern);
        $this->byName[$name] = count($this->routes);
        $this->routes[] = ['methods' => explode('|', strtoupper($methods)), 'pattern' => $pattern, 'regex' => '~^' . $regex . '$~u',
            'params' => $params, 'handler' => $handler, 'name' => $name];
    }

    /** [route, params] | 405 | null */
    public function match(string $method, string $path): array|int|null
    {
        $allowed = false;
        foreach ($this->routes as $r) {
            if (preg_match($r['regex'], $path, $m)) {
                $methods = $r['methods'];
                if (in_array('GET', $methods, true)) {
                    $methods[] = 'HEAD';
                }
                if (!in_array($method, $methods, true)) {
                    $allowed = true;
                    continue;
                }
                $params = [];
                foreach ($r['params'] as $p => $conv) {
                    $params[$p] = $conv === 'int' ? (int) $m[$p] : $m[$p];
                }
                return [$r, $params];
            }
        }
        return $allowed ? 405 : null;
    }

    /** Build the address of a named route; unknown parameters become the query string (as url_for). */
    public function url(string $name, array $params = []): string
    {
        if (!isset($this->byName[$name])) {
            throw new \InvalidArgumentException("No route named {$name}");
        }
        $r = $this->routes[$this->byName[$name]];
        $used = [];
        $path = preg_replace_callback('/<(?:(\w+)(?:\(([^)]*)\))?:)?(\w+)>/', function ($m) use ($params, &$used) {
            $used[$m[3]] = true;
            if (!array_key_exists($m[3], $params)) {
                throw new \InvalidArgumentException("Missing {$m[3]}");
            }
            return $m[1] === 'path' ? str_replace('%2F', '/', rawurlencode((string) $params[$m[3]])) : rawurlencode((string) $params[$m[3]]);
        }, $r['pattern']);
        $rest = [];
        foreach ($params as $k => $v) {
            if (!isset($used[$k]) && $v !== null) {
                $rest[$k] = $v;
            }
        }
        return $rest ? $path . '?' . http_build_query($rest, '', '&', PHP_QUERY_RFC3986) : $path;
    }

    public function has(string $name): bool
    {
        return isset($this->byName[$name]);
    }
}
