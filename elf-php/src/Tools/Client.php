<?php
declare(strict_types=1);

namespace Elf\Tools;

use Elf\App;
use Elf\Http\Request;
use Elf\Http\Response;
use Elf\Http\Session;

/**
 * The site's own forms, used from inside the process (as Flask's test client): requests go through App::handle with
 * this client's cookies. Used by the sample builder and the tests. The CSRF token is pinned, as in the tests.
 */
final class Client
{
    public const TOKEN = 'sample-builder-csrf';
    /** @var array<string,string> */
    public array $cookies = [];

    public function __construct(private readonly App $app, ?string $username = null, ?string $password = null)
    {
        if ($username !== null) {
            $r = $this->post('/auth/login', ['identifier' => $username, 'password' => (string) $password]);
            if ($r->status !== 302) {
                throw new \RuntimeException("sample: could not sign in as {$username}");
            }
        }
    }

    public function get(string $url, array $headers = []): Response
    {
        return $this->send(Request::create('GET', $url, [], [], $headers, $this->cookies));
    }

    /**
     * POST a form. $files: field name => [path, filename] of a file on disk.
     * @param array<string, string|string[]> $data
     */
    public function post(string $url, array $data = [], array $files = [], array $headers = []): Response
    {
        $this->pinCsrf();
        $data['csrf_token'] = self::TOKEN;
        $up = [];
        foreach ($files as $name => [$path, $filename]) {
            $up[$name] = ['path' => $path, 'name' => $filename, 'size' => (int) filesize($path), 'error' => UPLOAD_ERR_OK];
        }
        return $this->send(Request::create('POST', $url, $data, $up, $headers, $this->cookies));
    }

    /** The session cookie with the known CSRF token in it (as session_transaction in the Python tests). */
    private function pinCsrf(): void
    {
        $s = new Session((string) $this->app->config['SECRET_KEY']);
        $s->load($this->cookies[Session::COOKIE] ?? null);
        $s->set('csrf', self::TOKEN);
        $this->cookies[Session::COOKIE] = $s->serialize((int) $this->app->config['SESSION_LIFETIME_SECONDS']);
    }

    private function send(Request $req): Response
    {
        $r = $this->app->handle($req);
        foreach ($r->cookies as $raw) {
            $parts = explode(';', $raw);
            [$name, $value] = array_pad(explode('=', trim($parts[0]), 2), 2, '');
            $name = rawurldecode($name);
            if (stripos($raw, 'Max-Age=0') !== false || $value === '') {
                unset($this->cookies[$name]);
            } else {
                $this->cookies[$name] = rawurldecode($value);
            }
        }
        return $r;
    }
}
