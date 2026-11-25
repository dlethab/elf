<?php
declare(strict_types=1);

namespace Elf\Http;

/** One HTTP response: a body, or a file streamed from disk (with byte ranges for audio and video). */
final class Response
{
    /** @var array<string, string[]> */
    public array $headers = [];
    /** @var array<int, string> raw Set-Cookie values */
    public array $cookies = [];
    public ?string $file = null;
    /** @var array{0:int,1:int}|null byte range of $file to send */
    public ?array $range = null;

    public function __construct(public string $body = '', public int $status = 200, array $headers = [])
    {
        foreach ($headers as $k => $v) {
            $this->set($k, $v);
        }
        if (!$this->has('Content-Type')) {
            $this->set('Content-Type', 'text/html; charset=utf-8');
        }
    }

    private static function norm(string $name): string
    {
        return implode('-', array_map('ucfirst', explode('-', strtolower($name))));
    }

    public function set(string $name, string $value): self
    {
        $this->headers[self::norm($name)] = [$value];
        return $this;
    }

    public function add(string $name, string $value): self
    {
        $this->headers[self::norm($name)][] = $value;
        return $this;
    }

    public function get(string $name): ?string
    {
        $v = $this->headers[self::norm($name)] ?? null;
        return $v ? implode(', ', $v) : null;
    }

    public function has(string $name): bool
    {
        return isset($this->headers[self::norm($name)]);
    }

    public function remove(string $name): void
    {
        unset($this->headers[self::norm($name)]);
    }

    public function setCookie(string $name, string $value, int $maxAge = 0, string $path = '/', bool $httpOnly = true,
                              bool $secure = false, string $sameSite = 'Lax', ?int $expires = null): void
    {
        $c = rawurlencode($name) . '=' . rawurlencode($value) . "; Path={$path}; SameSite={$sameSite}";
        if ($maxAge > 0) {
            $c .= "; Max-Age={$maxAge}; Expires=" . gmdate('D, d M Y H:i:s \G\M\T', time() + $maxAge);
        } elseif ($expires !== null) {
            $c .= '; Max-Age=0; Expires=' . gmdate('D, d M Y H:i:s \G\M\T', $expires);
        }
        if ($httpOnly) {
            $c .= '; HttpOnly';
        }
        if ($secure) {
            $c .= '; Secure';
        }
        $this->cookies[] = $c;
    }

    public static function redirect(string $location, int $status = 302): self
    {
        $r = new self('', $status);
        $r->set('Location', $location);
        return $r;
    }

    public static function json(mixed $data, int $status = 200): self
    {
        $body = json_encode($data, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRESERVE_ZERO_FRACTION | JSON_INVALID_UTF8_SUBSTITUTE);
        return new self((string) $body, $status, ['Content-Type' => 'application/json']);
    }

    /** The body as the browser receives it (for tests). */
    public function data(): string
    {
        if ($this->file !== null) {
            $data = (string) file_get_contents($this->file);
            return $this->range ? substr($data, $this->range[0], $this->range[1] - $this->range[0] + 1) : $data;
        }
        return $this->body;
    }

    public function getJson(): mixed
    {
        return json_decode($this->data(), true);
    }

    public function send(): void
    {
        http_response_code($this->status);
        header_remove('X-Powered-By');
        foreach ($this->headers as $name => $values) {
            foreach ($values as $i => $v) {
                header("{$name}: {$v}", $i === 0);
            }
        }
        foreach ($this->cookies as $c) {
            header('Set-Cookie: ' . $c, false);
        }
        if ($this->status === 304 || ($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'HEAD') {
            return;
        }
        if ($this->file !== null) {
            $f = fopen($this->file, 'rb');
            [$start, $end] = $this->range ?? [0, filesize($this->file) - 1];
            fseek($f, $start);
            $left = $end - $start + 1;
            while ($left > 0 && !feof($f)) {
                $chunk = fread($f, (int) min(1024 * 1024, $left));
                if ($chunk === false) {
                    break;
                }
                echo $chunk;
                $left -= strlen($chunk);
                flush();
            }
            fclose($f);
            return;
        }
        echo $this->body;
    }
}
