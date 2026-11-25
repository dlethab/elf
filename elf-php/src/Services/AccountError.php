<?php
declare(strict_types=1);

namespace Elf\Services;

/** Validation errors for account forms, keyed by field name ("form" for the whole form). */
final class AccountError extends \RuntimeException
{
    public function __construct(public readonly array $errors)
    {
        parent::__construct(implode('; ', array_map(fn ($k, $v) => "{$k}: {$v}", array_keys($errors), $errors)));
    }
}
