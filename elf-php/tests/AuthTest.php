<?php
declare(strict_types=1);

namespace Elf\Tests;

use Elf\Http\Request;
use Elf\Services\Mfa;
use Elf\Services\Passwords;

/** Registration, sign-in, two-step sign-in, sessions, lockout, verification and password reset. */
final class AuthTest extends TestCase
{
    private function lastLink(string $path): string
    {
        $body = (string) $this->db->val('SELECT body FROM outbox ORDER BY id DESC LIMIT 1');
        $this->assertMatchesRegularExpression('~' . preg_quote($path, '~') . '[A-Za-z0-9_-]+~', $body);
        preg_match('~(' . preg_quote($path, '~') . '[A-Za-z0-9_-]+)~', $body, $m);
        return $m[1];
    }

    public function testRegistrationVerificationAndResetFlow(): void
    {
        $c = $this->client();
        $r = $c->post('/auth/register', ['email' => 'new@example.test', 'username' => 'newbie', 'display_name' => 'New Person',
            'password' => 'a long enough passphrase', 'password2' => 'a long enough passphrase']);
        $this->assertSame('/dashboard', $r->get('Location'));
        $this->assertStatus(200, $c->get('/dashboard'));
        $this->assertNull($this->db->val("SELECT email_verified_at FROM users WHERE username='newbie'"));
        $c->get($this->lastLink('/auth/verify/'));
        $this->assertNotNull($this->db->val("SELECT email_verified_at FROM users WHERE username='newbie'"));

        // reset: identical answer for unknown addresses; the link changes the password once
        $anon = $this->client();
        $this->assertSame('/auth/login', $anon->post('/auth/forgot', ['email' => 'nobody@example.test'])->get('Location'));
        $anon->post('/auth/forgot', ['email' => 'new@example.test']);
        $link = $this->lastLink('/auth/reset/');
        $this->assertStatus(200, $anon->get($link));
        $this->assertSame('/auth/login', $anon->post($link, ['password' => 'another long passphrase', 'password2' => 'another long passphrase'])->get('Location'));
        $this->assertStatus(400, $anon->get($link));                         // used
        $this->assertSame('/dashboard', $this->client()->post('/auth/login', ['identifier' => 'newbie', 'password' => 'another long passphrase'])->get('Location'));
        $this->assertStatus(302, $c->get('/dashboard'), 'the reset signs out other sessions');
    }

    public function testRegistrationErrorsAreAccessible(): void
    {
        $r = $this->client()->post('/auth/register', ['email' => 'not-an-email', 'username' => 'x', 'password' => 'short', 'password2' => 'short']);
        $this->assertStatus(400, $r);
        $this->assertStringContainsString('id="error-summary"', $r->data());
        $this->assertStringContainsString('aria-invalid="true"', $r->data());
        $this->assertStatus(400, $this->client()->post('/auth/register', ['website' => 'bot']));   // honeypot
    }

    public function testLogoutRevokesSessionServerSide(): void
    {
        $this->makeUser('leaver');
        $c = $this->client('leaver');
        $saved = $c->cookies;
        $c->post('/auth/logout');
        $r = $this->app->handle(Request::create('GET', '/dashboard', [], [], [], $saved));          // the old cookie, replayed
        $this->assertStatus(302, $r);
        $this->assertNotNull($this->db->val('SELECT revoked_at FROM user_sessions LIMIT 1'));
    }

    public function testLoginLockoutAfterRepeatedFailures(): void
    {
        $this->makeUser('target');
        $c = $this->client();
        for ($i = 0; $i < 5; $i++) {
            $this->assertStringContainsString('do not match', $c->post('/auth/login', ['identifier' => 'target', 'password' => 'wrong'])->data());
        }
        $r = $c->post('/auth/login', ['identifier' => 'target', 'password' => self::PASSWORD]);
        $this->assertStringContainsString('Too many failed attempts', $r->data());
        $this->assertStringNotContainsString('wrong', (string) $this->db->val("SELECT GROUP_CONCAT(detail_json) FROM audit_logs"));   // no secrets logged
    }

    public function testDeactivationEndsSessions(): void
    {
        $admin = $this->makeUser('boss', ['administrator']);
        $u = $this->makeUser('gone');
        $c = $this->client('gone');
        $this->assertStatus(200, $c->get('/dashboard'));
        $this->client('boss')->post("/admin/users/{$u->id}/deactivate");
        $this->assertStatus(302, $c->get('/dashboard'));
        $this->assertStringContainsString('do not match', $this->client()->post('/auth/login', ['identifier' => 'gone', 'password' => self::PASSWORD])->data());
        $this->assertSame(1, (int) $this->db->val("SELECT COUNT(*) FROM audit_logs WHERE action LIKE 'account.deactivated%' AND actor_id=?", [$admin->id]));
    }

    public function testTwoStepSignIn(): void
    {
        $u = $this->makeUser('careful');
        $secret = Mfa::newSecret();
        $codes = Mfa::enable($this->db, $u->id, $secret, Mfa::codeAt($secret));
        $this->assertCount(10, $codes);
        $c = $this->client();
        $r = $c->post('/auth/login', ['identifier' => 'careful', 'password' => self::PASSWORD]);
        $this->assertSame('/auth/two-step', $r->get('Location'));
        $this->assertStatus(302, $c->get('/dashboard'), 'not signed in until the second step');
        $this->assertStatus(400, $c->post('/auth/two-step', ['code' => '000000']));
        $this->assertSame('/dashboard', $c->post('/auth/two-step', ['code' => $codes[0]])->get('Location'));   // a recovery code, once
        $this->assertStatus(200, $c->get('/dashboard'));
        $again = $this->client();
        $again->post('/auth/login', ['identifier' => 'careful', 'password' => self::PASSWORD]);
        $this->assertStatus(400, $again->post('/auth/two-step', ['code' => $codes[0]]));
    }

    public function testSecurityPageShowsQrCodeForSetup(): void
    {
        $this->makeUser('setup');
        $c = $this->client('setup');
        $r = $c->post('/dashboard/security', ['op' => 'start']);
        $this->assertStatus(200, $r);
        $this->assertStringContainsString('data:image/svg+xml', $r->data());
        $this->assertMatchesRegularExpression('~<code dir="ltr" class="secret">[A-Z2-7]{16,}</code>~', $r->data());   // the key, to type in
    }

    public function testPythonEditionPasswordHashes(): void
    {
        // werkzeug.security.generate_password_hash("correct-horse-battery-staple", method="pbkdf2:sha256:1000", salt "abcdefgh") form
        $salt = 'NaClNaClNaClNaCl';
        $hash = 'pbkdf2:sha256:1000$' . $salt . '$' . hash_pbkdf2('sha256', self::PASSWORD, $salt, 1000);
        $this->assertTrue(Passwords::verify($hash, self::PASSWORD));
        $this->assertFalse(Passwords::verify($hash, 'wrong'));
        $this->assertFalse(Passwords::supported('scrypt:32768:8:1$abc$def'));
        $this->assertFalse(Passwords::verify('scrypt:32768:8:1$abc$def', self::PASSWORD));
        $this->db->exec("INSERT INTO users(email, username, display_name, password_hash, email_verified_at) VALUES ('py@example.test','pyuser','Py',?,'2000-01-01T00:00:00Z')", [$hash]);
        $this->assertSame('/dashboard', $this->client()->post('/auth/login', ['identifier' => 'pyuser', 'password' => self::PASSWORD])->get('Location'));
    }

    public function testUnverifiedUserCanDraftButNotSubmit(): void
    {
        $this->makeUser('fresh', [], false);
        $c = $this->client('fresh');
        $r = $c->post('/contribute/person', ['preferred_name' => 'Testperson Unverified (FICTIONAL)', 'living_status' => 'deceased', 'action' => 'draft']);
        $this->assertStatus(302, $r);
        $sid = (int) $this->db->val('SELECT MAX(id) FROM submissions');
        $c->post("/dashboard/submissions/{$sid}/submit");
        $this->assertSame('draft', $this->db->val('SELECT status FROM submissions WHERE id=?', [$sid]));
    }
}
