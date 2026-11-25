<?php
declare(strict_types=1);

namespace Elf\Http;

/**
 * The visitor's session, kept in a signed cookie (as Flask does): small values only (the sign-in token, the CSRF
 * token, flash messages, a pending two-step sign-in). Signed with HMAC-SHA256 under the secret key, so it cannot be
 * altered; the sign-in token in it is checked against the database on every request.
 */
final class Session
{
    public const COOKIE = 'elf_session';
    public array $data = [];
    public bool $modified = false;
    public bool $permanent = false;

    public function __construct(private readonly string $secret)
    {
    }

    public function load(?string $cookie): void
    {
        $this->data = [];
        if (!$cookie || !str_contains($cookie, '.')) {
            return;
        }
        [$payload, $sig] = explode('.', $cookie, 2);
        if (!hash_equals(hash_hmac('sha256', $payload, $this->secret), $sig)) {
            return;
        }
        $data = json_decode((string) base64_decode(strtr($payload, '-_', '+/'), true), true);
        if (is_array($data) && isset($data['d']) && is_array($data['d'])) {
            if (isset($data['x']) && (int) $data['x'] < time()) {
                return;                                    // an expired permanent session
            }
            $this->data = $data['d'];
            $this->permanent = isset($data['x']);
        }
    }

    public function get(string $k, mixed $default = null): mixed
    {
        return $this->data[$k] ?? $default;
    }

    public function set(string $k, mixed $v): void
    {
        $this->data[$k] = $v;
        $this->modified = true;
    }

    public function pop(string $k, mixed $default = null): mixed
    {
        if (!array_key_exists($k, $this->data)) {
            return $default;
        }
        $v = $this->data[$k];
        unset($this->data[$k]);
        $this->modified = true;
        return $v;
    }

    public function has(string $k): bool
    {
        return array_key_exists($k, $this->data);
    }

    public function clear(): void
    {
        $this->data = [];
        $this->permanent = false;
        $this->modified = true;
    }

    /** The cookie value, or '' to delete it. */
    public function serialize(int $lifetime): string
    {
        if (!$this->data) {
            return '';
        }
        $wrap = ['d' => $this->data];
        if ($this->permanent) {
            $wrap['x'] = time() + $lifetime;
        }
        $payload = rtrim(strtr(base64_encode((string) json_encode($wrap, JSON_UNESCAPED_SLASHES)), '+/', '-_'), '=');
        return $payload . '.' . hash_hmac('sha256', $payload, $this->secret);
    }
}
