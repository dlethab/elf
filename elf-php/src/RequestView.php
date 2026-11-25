<?php
declare(strict_types=1);

namespace Elf;

/** `request` in templates: path, full_path, args, form and endpoint of the current request (as Flask's). */
final class RequestView
{
    public function __construct(private readonly App $app)
    {
    }

    public function __isset(string $k): bool
    {
        return in_array($k, ['path', 'full_path', 'args', 'form', 'endpoint', 'view_args', 'method'], true);
    }

    public function __get(string $k): mixed
    {
        $r = $this->app->req;
        if (!$r) {
            return null;
        }
        return match ($k) {
            'path' => $r->path,
            'full_path' => $r->fullPath(),
            'args' => $r->query,
            'form' => $r->form,
            'endpoint' => $r->endpoint,
            'view_args' => $r->viewArgs,
            'method' => $r->method,
            default => null,
        };
    }
}
