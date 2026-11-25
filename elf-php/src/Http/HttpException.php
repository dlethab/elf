<?php
declare(strict_types=1);

namespace Elf\Http;

/** abort(code): stops the request with an error page (the description is shown only for 400, as in the Python edition). */
final class HttpException extends \RuntimeException
{
    public function __construct(public readonly int $status, public readonly ?string $description = null)
    {
        parent::__construct((string) $description, $status);
    }
}
