<?php
declare(strict_types=1);

namespace Elf\Http;

/** Thrown to end a request with a redirect (used by the sign-in and permission guards). */
final class Redirect extends \RuntimeException
{
    public function __construct(public readonly string $location)
    {
        parent::__construct($location);
    }
}
