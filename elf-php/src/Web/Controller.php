<?php
declare(strict_types=1);

namespace Elf\Web;

use Elf\App;
use Elf\Db;
use Elf\Http\HttpException;
use Elf\Http\Redirect;
use Elf\Http\Request;
use Elf\Http\Response;
use Elf\I18n;
use Elf\Security;
use Elf\Services\CurrentUser;

/** Shared helpers for the route classes (the Python edition's Flask blueprints). */
abstract class Controller
{
    public function __construct(protected readonly App $app)
    {
    }

    /** Register a route whose parameters are passed to $method in order. */
    protected function route(string $methods, string $pattern, string $method, string $name): void
    {
        $this->app->router->add($methods, $pattern, fn (array $p) => $this->$method(...array_values($p)), $name);
    }

    protected function db(): Db
    {
        return $this->app->db();
    }

    protected function req(): Request
    {
        return $this->app->req;
    }

    protected function viewer(): ?CurrentUser
    {
        return $this->app->user;
    }

    /** The signed-in user (callers have already checked that someone is signed in). */
    protected function me(): CurrentUser
    {
        if (!$this->app->user) {
            throw new HttpException(403);
        }
        return $this->app->user;
    }

    protected function render(string $template, array $context = [], int $status = 200): Response
    {
        return $this->app->render($template, $context, $status);
    }

    protected function abort(int $code, ?string $description = null): never
    {
        throw new HttpException($code, $description);
    }

    protected function redirect(string $location, int $status = 302): Response
    {
        return Response::redirect($location, $status);
    }

    protected function url(string $name, array $params = []): string
    {
        return $this->app->url($name, $params);
    }

    protected function flash(string $message, string $category = 'message'): void
    {
        $this->app->flash($message, $category);
    }

    protected function json(mixed $data, int $status = 200): Response
    {
        return Response::json($data, $status);
    }

    protected function ip(): string
    {
        return $this->app->ip();
    }

    protected function isPost(): bool
    {
        return $this->req()->method === 'POST';
    }

    /** request.form.get(k) with "" for a missing field, trimmed. */
    protected function f(string $k): string
    {
        return trim((string) $this->req()->post($k, ''));
    }

    protected function arg(string $k, ?string $default = null): ?string
    {
        return $this->req()->arg($k, $default);
    }

    /** ?page=, between 1 and 10000. */
    protected function page(): int
    {
        return max(1, min($this->req()->argInt('page', 1), 10000));
    }

    protected function loginRequired(): void
    {
        Security::loginRequired($this->app);
    }

    protected function requirePerm(string $permission): void
    {
        Security::requirePerm($this->app, $permission);
    }

    protected function _(?string $text, array $kw = []): ?string
    {
        return I18n::gettext($text, $kw);
    }

    /** Python's s[:n] for text. */
    protected static function cut(?string $s, int $n): string
    {
        return mb_substr((string) $s, 0, $n);
    }

    protected function throwRedirect(string $location): never
    {
        throw new Redirect($location);
    }
}
