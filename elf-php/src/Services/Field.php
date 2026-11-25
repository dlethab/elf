<?php
declare(strict_types=1);

namespace Elf\Services;

/** One field of a contribution form (see Specs). */
final class Field
{
    /**
     * @param string $kind text|area|choice|date|ref|refs|consents|taxon|lines|sources|float|url
     * @param array<int,array{0:string,1:string}>|null $choices
     */
    public function __construct(
        public readonly string $name,
        public readonly string $label,
        public readonly string $kind = 'text',
        public readonly bool $required = false,
        public readonly int $max = 200,
        public readonly ?array $choices = null,
        public readonly string $help = '',
        public readonly int $rows = 4,
        public readonly bool $additive = false,     // corrections only ADD (aliases, sources) and never delete
        public readonly ?string $ref = null,        // entity kind a "ref" field points at
    ) {
    }
}
