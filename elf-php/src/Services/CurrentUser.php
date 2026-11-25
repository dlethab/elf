<?php
declare(strict_types=1);

namespace Elf\Services;

use Elf\Permissions;

/** The signed-in user, with their roles and permissions (read-only for the length of a request). */
final class CurrentUser
{
    /** @var array<string,true> */
    private array $perms;

    public function __construct(
        public readonly int $id,
        public readonly string $email,
        public readonly string $username,
        public readonly string $display_name,
        public readonly array $roles,
        public readonly bool $email_verified,
        public readonly bool $mfa_enabled = false,
    ) {
        $this->perms = Permissions::permissionsFor($roles);
    }

    public function can(string $perm): bool
    {
        return isset($this->perms[$perm]);
    }

    public function permissions(): array
    {
        return array_keys($this->perms);
    }

    public function withMfa(bool $on): self
    {
        return new self($this->id, $this->email, $this->username, $this->display_name, $this->roles, $this->email_verified, $on);
    }
}
