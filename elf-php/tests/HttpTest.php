<?php
declare(strict_types=1);

namespace Elf\Tests;

use Elf\Http\Request;
use Elf\Security;
use Elf\Tools\Client;

/** Security headers, caching, CSRF, redirects, errors and the public navigation, over HTTP. */
final class HttpTest extends TestCase
{
    public function testEveryMainNavItemOpens(): void
    {
        foreach (['/', '/people', '/families', '/places', '/events', '/sources', '/organizations', '/map', '/timeline', '/explore',
                  '/archive', '/collections', '/oral-histories', '/community', '/about', '/search?q=test', '/contact',
                  '/privacy', '/terms', '/copyright', '/accessibility', '/data-policy', '/standards', '/how-to-contribute', '/corrections',
                  '/auth/login', '/auth/register', '/auth/forgot', '/explore/curated', '/community/rules'] as $url) {
            $this->assertStatus(200, $this->get($url), $url);
        }
    }

    public function testHeadersAndCachePolicy(): void
    {
        $r = $this->get('/');
        $this->assertStringContainsString("default-src 'self'", $r->get('Content-Security-Policy'));
        $this->assertStringContainsString("frame-ancestors 'none'", $r->get('Content-Security-Policy'));
        $this->assertSame('DENY', $r->get('X-Frame-Options'));
        $this->assertSame('nosniff', $r->get('X-Content-Type-Options'));
        $this->assertSame('strict-origin-when-cross-origin', $r->get('Referrer-Policy'));
        $this->assertSame('public, max-age=0, must-revalidate', $r->get('Cache-Control'));
        $this->assertStringContainsString('Cookie', (string) $r->get('Vary'));
        $this->assertNull($r->get('Strict-Transport-Security'));            // https-only header in production only

        $login = $this->get('/auth/login');
        $this->assertSame('private, no-store', $login->get('Cache-Control'));
        $this->assertSame('noindex, nofollow', $login->get('X-Robots-Tag'));

        $this->makeUser('hdr');
        $signedIn = $this->client('hdr')->get('/');
        $this->assertSame('private, no-store', $signedIn->get('Cache-Control'));   // anything personalised is never cached

        $css = $this->get('/static/css/archive.css?v=abc');
        $this->assertStatus(200, $css);
        $this->assertSame('public, max-age=31536000, immutable', $css->get('Cache-Control'));
        $this->assertStringStartsWith('text/css', $css->get('Content-Type'));
        $this->assertSame('public, max-age=3600', $this->get('/static/css/archive.css')->get('Cache-Control'));
    }

    public function testStaticFilesStayInsideTheStaticFolder(): void
    {
        foreach (['/static/../../composer.json', '/static/..%2F..%2Fcomposer.json', '/static/', '/static/nope.css'] as $url) {
            $this->assertStatus(404, $this->get($url), $url);
        }
        $this->assertMatchesRegularExpression('~^/static/css/archive\.css\?v=[0-9a-f]+$~', $this->app->staticUrl('css/archive.css'));
    }

    public function testFramingOnlyForListedSitesAndOnlyTheEmbeddedAtlas(): void
    {
        $this->assertSame('DENY', $this->get('/explore?embed=1')->get('X-Frame-Options'));      // no sites listed: nobody may frame
        $this->app = $this->makeApp(['EMBED_ORIGINS' => 'https://elfveterans.org']);
        $r = $this->get('/explore?embed=1');
        $this->assertStringContainsString('frame-ancestors https://elfveterans.org', $r->get('Content-Security-Policy'));
        $this->assertNull($r->get('X-Frame-Options'));
        $this->assertStringNotContainsString('class="site-header"', $r->data());              // embedded layout: no site header
        foreach (['/explore', '/auth/login', '/people?embed=1'] as $url) {
            $this->assertSame('DENY', $this->get($url)->get('X-Frame-Options'), $url);
        }
        $this->expectException(\RuntimeException::class);
        $this->makeApp(['EMBED_ORIGINS' => 'javascript:alert(1)']);
    }

    public function testCsrfRequiredOnEveryPost(): void
    {
        $this->makeUser('csrf');
        $c = $this->client('csrf');
        foreach (['/auth/logout', '/contribute/person', '/dashboard/profile', '/contact', '/community/report', '/editor/bulk'] as $url) {
            $r = $this->app->handle(Request::create('POST', $url, ['csrf_token' => 'wrong'], [], [], $c->cookies));
            $this->assertStatus(400, $r, $url);
            $this->assertStringContainsString('Your session expired or the form was invalid', $r->data());
        }
        // the header form (used by the scripts) is accepted
        $r = $this->app->handle(Request::create('POST', '/dashboard/notifications', [], [], ['X-CSRF-Token' => Client::TOKEN], $this->pinned($c)));
        $this->assertStatus(302, $r);
    }

    /** The client's cookies with the known CSRF token in the session. */
    private function pinned(Client $c): array
    {
        $s = new \Elf\Http\Session(str_repeat('t', 40));
        $s->load($c->cookies[\Elf\Http\Session::COOKIE] ?? null);
        $s->set('csrf', Client::TOKEN);
        return [\Elf\Http\Session::COOKIE => $s->serialize(3600)] + $c->cookies;
    }

    public function testSessionCookieCannotBeForged(): void
    {
        $u = $this->makeUser('forge');
        $raw = \Elf\Services\Accounts::createSession($this->db, $u->id, '127.0.0.1', 'test', 3600);
        $other = new \Elf\Http\Session('a-different-secret-key-that-is-long-enough');
        $other->set('sid', $raw);
        $r = $this->app->handle(Request::create('GET', '/dashboard', [], [], [], [\Elf\Http\Session::COOKIE => $other->serialize(3600)]));
        $this->assertStatus(302, $r);                                           // treated as signed out
        $this->assertStringStartsWith('/auth/login', $r->get('Location'));
    }

    public function testOpenRedirectBlocked(): void
    {
        foreach (['//evil.test', 'https://evil.test', '/\\evil.test', 'javascript:alert(1)', 'evil.test', ''] as $bad) {
            $this->assertSame('/', Security::safeNext($bad), $bad);
        }
        $this->assertSame('/people?letter=A', Security::safeNext('/people?letter=A'));
        $r = $this->get('/language/ar?next=//evil.test');
        $this->assertSame('/', $r->get('Location'));
        $this->assertStringContainsString('elf_lang=ar', implode(';', $r->cookies));
        $this->makeUser('nxt');
        $r = $this->client()->post('/auth/login', ['identifier' => 'nxt', 'password' => self::PASSWORD, 'next' => 'https://evil.test/']);
        $this->assertSame('/dashboard', $r->get('Location'));
    }

    public function testErrorPages(): void
    {
        $r = $this->get('/no/such/page');
        $this->assertStatus(404, $r);
        $this->assertStringContainsString('This page does not exist or is not publicly available.', $r->data());
        $this->assertStatus(405, $this->app->handle(Request::create('GET', '/auth/logout')));
        $this->assertStatus(404, $this->get('/people/no-such-person'));
        $this->assertStatus(404, $this->get('/id/per-00000000'));
    }

    public function testRobotsSitemapAndJson(): void
    {
        $r = $this->get('/robots.txt');
        $this->assertStringContainsString('Disallow: /dashboard', $r->data());
        $this->assertStringContainsString('<urlset', $this->get('/sitemap.xml')->data());
        $this->assertSame(['places' => []], $this->get('/map/data.json')->getJson());
        $this->assertSame(['events' => []], $this->get('/timeline/data.json')->getJson());
        $this->assertSame(['n' => 0], $this->get('/explore/context.json')->getJson());
        $this->assertStatus(404, $this->get('/map/review.json'));               // reviewers only
    }

    public function testContactFormHoneypotAndStorage(): void
    {
        $c = $this->client();
        $r = $c->post('/contact', ['message' => 'short']);
        $this->assertStatus(200, $r);
        $this->assertStringContainsString('Write between 10 and 5,000 characters.', $r->data());
        $c->post('/contact', ['message' => 'A message long enough to be stored.', 'website' => 'http://spam.test']);
        $this->assertSame(0, (int) $this->db->val('SELECT COUNT(*) FROM contact_messages'));
        $r = $c->post('/contact', ['message' => 'A message long enough to be stored.', 'email' => 'reader@example.test']);
        $this->assertStatus(302, $r);
        $this->assertSame(1, (int) $this->db->val('SELECT COUNT(*) FROM contact_messages'));
    }

    public function testProductionRefusesInsecureConfigAndHidesDevRoutes(): void
    {
        foreach ([['SECRET_KEY' => 'short'], ['SECRET_KEY' => str_repeat('s', 40), 'BASE_URL' => 'http://example.org']] as $bad) {
            try {
                $this->makeApp(['ENV' => 'production', 'BASE_URL' => 'https://example.org'] + $bad);
                $this->fail('insecure production config accepted');
            } catch (\RuntimeException) {
                $this->addToAssertionCount(1);
            }
        }
        $this->app = $this->makeApp(['ENV' => 'production', 'SECRET_KEY' => str_repeat('s', 40), 'BASE_URL' => 'https://example.org',
            'TEMPLATE_CACHE' => sys_get_temp_dir() . '/elf-test-twig-' . bin2hex(random_bytes(3))]);
        $this->assertStatus(404, $this->get('/dev/outbox'));
        $r = $this->get('/');
        $this->assertSame('max-age=31536000; includeSubDomains', $r->get('Strict-Transport-Security'));
        self::rmtree($this->app->config['TEMPLATE_CACHE']);
    }

    public function testRangeRequestsForMedia(): void
    {
        $file = tempnam(sys_get_temp_dir(), 'elf');
        file_put_contents($file, str_repeat('0123456789', 10));
        $r = \Elf\Web\StaticFiles::sendFile(Request::create('GET', '/x', [], [], ['Range' => 'bytes=10-19']), $file, 'audio/mpeg');
        $this->assertSame(206, $r->status);
        $this->assertSame('bytes 10-19/100', $r->get('Content-Range'));
        $this->assertSame('0123456789', $r->data());
        $etag = $r->get('ETag');
        $this->assertSame(304, \Elf\Web\StaticFiles::sendFile(Request::create('GET', '/x', [], [], ['If-None-Match' => $etag]), $file, 'audio/mpeg')->status);
        $this->assertSame(416, \Elf\Web\StaticFiles::sendFile(Request::create('GET', '/x', [], [], ['Range' => 'bytes=500-']), $file, 'audio/mpeg')->status);
        unlink($file);
    }

    public function testRepeatedFormFieldsKeepEveryValueAndTheFirstWins(): void
    {
        [$first, $lists] = Request::parseQs('sid=1&sid=2&a.b=x+y&q=%E2%80%93');
        $this->assertSame(['sid' => '1', 'a.b' => 'x y', 'q' => '–'], $first);
        $this->assertSame(['1', '2'], $lists['sid']);
    }
}
