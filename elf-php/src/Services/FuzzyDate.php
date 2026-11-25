<?php
declare(strict_types=1);

namespace Elf\Services;

final class FuzzyDate
{
    public function __construct(
        public readonly ?string $start = null,
        public readonly ?string $end = null,
        public readonly string $precision = 'unknown',
        public readonly ?string $note = null,
    ) {
    }

    public function asArray(): array
    {
        return ['start' => $this->start, 'end' => $this->end, 'precision' => $this->precision, 'note' => $this->note];
    }
}
