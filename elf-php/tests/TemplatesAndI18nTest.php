<?php
declare(strict_types=1);

namespace Elf\Tests;

use Elf\Config;
use Elf\I18n;
use Elf\Http\Request;
use Elf\View;

/** Every template compiles; interface languages, right-to-left layout and the Jinja-compatible filters. */
final class TemplatesAndI18nTest extends TestCase
{
    public function testEveryTemplateCompiles(): void
    {
        $root = Config::root() . '/templates';
        $n = 0;
        $it = new \RecursiveIteratorIterator(new \RecursiveDirectoryIterator($root, \FilesystemIterator::SKIP_DOTS));
        foreach ($it as $f) {
            $name = str_replace('\\', '/', substr($f->getPathname(), strlen($root) + 1));
            $this->app->twig->load($name);                                       // throws on any syntax error
            $n++;
        }
        $this->assertGreaterThanOrEqual(87, $n);
    }

    public function testLanguagesAndRightToLeft(): void
    {
        $r = $this->app->handle(Request::create('GET', '/', [], [], [], [I18n::COOKIE => 'ar']));
        $this->assertStringContainsString('<html lang="ar" dir="rtl">', $r->data());
        $this->assertStringContainsString('notice--info lang-note', $r->data());     // the draft-translation notice
        $ti = $this->app->handle(Request::create('GET', '/', [], [], [], [I18n::COOKIE => 'ti']))->data();
        $this->assertStringContainsString('<html lang="ti" dir="ltr">', $ti);
        $odd = $this->app->handle(Request::create('GET', '/', [], [], [], [I18n::COOKIE => 'xx']))->data();
        $this->assertStringContainsString('<html lang="en" dir="ltr">', $odd);
        // staff pages and legal drafts are marked English-only
        $this->assertTrue(I18n::isEnglishOnly('editor.queue'));
        $this->assertTrue(I18n::isEnglishOnly('public.info', ['page' => 'privacy']));
        $this->assertFalse(I18n::isEnglishOnly('public.info', ['page' => 'about']));
        $p = $this->app->handle(Request::create('GET', '/privacy', [], [], [], [I18n::COOKIE => 'ar']))->data();
        $this->assertStringContainsString('<main id="main" tabindex="-1" lang="en" dir="ltr">', $p);
    }

    public function testGettextPlaceholdersAndFallback(): void
    {
        I18n::$current = 'en';
        $this->assertSame('3 published records', I18n::gettext('{n} published records', ['n' => 3]));
        $this->assertSame('{literal} 5', I18n::format('{{literal}} {n}', ['n' => 5]));
        $this->assertSame('1.5 and True', I18n::format('{a} and {b}', ['a' => 1.5, 'b' => true]));
        I18n::$current = 'ar';
        $this->assertSame('No such text in the catalogue', I18n::gettext('No such text in the catalogue'));   // English fallback
        $this->assertNotSame('Search', I18n::gettext('Search'));
        I18n::$current = 'en';
        $this->expectException(\OutOfBoundsException::class);
        I18n::format('{missing}', []);
    }

    public function testJinjaCompatibleFilters(): void
    {
        $j = View::tojson(['b' => "<script> & 'x' é", 'a' => 1]);
        $this->assertSame(['a' => 1, 'b' => "<script> & 'x' é"], json_decode($j, true));
        $this->assertStringStartsWith('{"a": 1, "b": "', $j);                         // keys sorted, Python's separators
        $this->assertSame(0, preg_match('/[<>&\'\x80-\xff]/', $j), $j);               // safe inside HTML and single-quoted attributes
        $this->assertStringContainsString(chr(92) . 'u003cscript' . chr(92) . 'u003e', $j);
        $this->assertSame('{}', View::tojson(new \stdClass()));
        $this->assertSame('[1.0, 2.5]', View::tojson([1.0, 2.5]));
        $this->assertSame('Hello wonderful...', View::truncate('Hello wonderful world of tests', 20));
        $this->assertSame('short', View::truncate('short', 3));                    // within the leeway: unchanged
        $this->assertSame('12.0', View::py(12.0));
        $this->assertSame('None', View::py(null));
    }

    public function testDatesAreShownWithTheirPrecision(): void
    {
        I18n::$current = 'en';
        $this->assertSame('c. 2099', I18n::fdate('2099', null, 'approximate'));
        $this->assertSame('Unknown', I18n::fdate(null, null, 'unknown'));
        $this->assertSame('14 March 1952', I18n::fdate('1952-03-14', '1952-03-14', 'exact'));
        $this->assertSame('1950s', I18n::fdate('1950', null, 'decade'));
    }
}
