<?php
declare(strict_types=1);

namespace Elf;

/** `g` in templates: the per-request values a view set on App::$g (e.g. "embed"). */
final class GView
{
    public function __construct(private readonly App $app)
    {
    }

    public function __isset(string $k): bool
    {
        return array_key_exists($k, $this->app->g);
    }

    public function __get(string $k): mixed
    {
        return $this->app->g[$k] ?? null;
    }
}
