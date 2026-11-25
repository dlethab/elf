<?php
declare(strict_types=1);

namespace Elf\Tests;

use Elf\App;
use Elf\Db;
use Elf\Http\Response;
use Elf\Services\Accounts;
use Elf\Services\CurrentUser;
use Elf\Services\Entities;
use Elf\Services\Records;
use Elf\Services\Workflow;
use Elf\Tools\Client;

/**
 * Each test gets a fresh in-memory database with every migration applied, and an App using it.
 * ALL data created here is synthetic and obviously fictional; it is never a historical claim.
 */
abstract class TestCase extends \PHPUnit\Framework\TestCase
{
    public const PASSWORD = 'correct-horse-battery-staple';
    public const CONFIG = ['REQUIRE_EMAIL_VERIFICATION' => true, 'ALLOW_SELF_REVIEW' => false];
    private static ?string $fastHash = null;
    protected Db $db;
    protected App $app;
    protected string $media;

    protected function setUp(): void
    {
        $this->db = new Db(':memory:');
        $this->db->migrate();
        $this->media = sys_get_temp_dir() . '/elf-test-media-' . bin2hex(random_bytes(4));
        $this->app = $this->makeApp();
    }

    protected function tearDown(): void
    {
        self::rmtree($this->media);
    }

    protected function makeApp(array $overrides = []): App
    {
        return new App($overrides + ['ENV' => 'testing', 'DATABASE_PATH' => ':memory:', '_SHARED_CONNECTION' => $this->db,
            'SECRET_KEY' => str_repeat('t', 40), 'MEDIA_ROOT' => $this->media, 'EMBED_ORIGINS' => ''], []);
    }

    /** One password hash for every test user (hashing is deliberately slow). */
    protected static function hash(): string
    {
        return self::$fastHash ??= password_hash(self::PASSWORD, PASSWORD_BCRYPT, ['cost' => 4]);
    }

    protected function makeUser(string $username, array $roles = [], bool $verified = true, bool $active = true): CurrentUser
    {
        $id = $this->db->insert('INSERT INTO users(email, username, display_name, password_hash, email_verified_at, is_active) VALUES (?,?,?,?,?,?)',
            ["{$username}@example.test", $username, ucfirst($username), self::hash(), $verified ? '2000-01-01T00:00:00Z' : null, (int) $active]);
        foreach ($roles as $r) {
            $this->db->exec('INSERT INTO user_roles(user_id, role) VALUES (?,?)', [$id, $r]);
        }
        return $this->cu($id);
    }

    protected function cu(int $id): CurrentUser
    {
        $r = $this->db->one('SELECT * FROM users WHERE id=?', [$id]);
        return new CurrentUser((int) $r['id'], $r['email'], $r['username'], $r['display_name'], Accounts::getRoles($this->db, $id),
            $r['email_verified_at'] !== null);
    }

    /** Validate → create → submit. Returns the submission id. */
    protected function submitNew(CurrentUser $user, string $kind, array $raw, ?array $target = null, ?array $family = null): int
    {
        [$clean, $errors] = Records::validate($this->db, $kind, $raw);
        $this->assertSame([], $errors);
        $sid = Workflow::create($this->db, $user, $kind, $clean, self::CONFIG, $target, $family);
        Workflow::transition($this->db, $user, $sid, 'submitted', self::CONFIG);
        return $sid;
    }

    protected function publish(CurrentUser $editor, int $sid, bool $consent = false): array
    {
        Workflow::transition($this->db, $editor, $sid, 'under_review', self::CONFIG);
        Workflow::transition($this->db, $editor, $sid, 'approved', self::CONFIG, 'Looks good');
        return Workflow::transition($this->db, $editor, $sid, 'published', self::CONFIG, null, null, $consent);
    }

    protected function publishNew(CurrentUser $contributor, CurrentUser $editor, string $kind, array $raw, bool $consent = false): array
    {
        $s = $this->publish($editor, $this->submitNew($contributor, $kind, $raw), $consent);
        return Entities::get($this->db, (int) $s['result_entity_id']);
    }

    /** A browser-like client, signed in when a username is given. */
    protected function client(?string $username = null): Client
    {
        return new Client($this->app, $username, $username ? self::PASSWORD : null);
    }

    protected function get(string $url): Response
    {
        return $this->client()->get($url);
    }

    protected function assertStatus(int $expected, Response $r, string $msg = ''): void
    {
        $this->assertSame($expected, $r->status, $msg . ' ' . substr(strip_tags($r->data()), 0, 300));
    }

    protected static function rmtree(string $dir): void
    {
        if (!is_dir($dir)) {
            return;
        }
        $it = new \RecursiveIteratorIterator(new \RecursiveDirectoryIterator($dir, \FilesystemIterator::SKIP_DOTS), \RecursiveIteratorIterator::CHILD_FIRST);
        foreach ($it as $f) {
            $f->isDir() ? rmdir($f->getPathname()) : unlink($f->getPathname());
        }
        rmdir($dir);
    }
}
