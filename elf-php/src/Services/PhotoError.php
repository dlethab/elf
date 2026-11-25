<?php
declare(strict_types=1);

namespace Elf\Services;

/** Validation problems, as {field: message}. Messages are English msgids (translated in templates). */
final class PhotoError extends \RuntimeException
{
    public function __construct(public readonly array $errors)
    {
        parent::__construct(implode('; ', $errors));
    }
}
