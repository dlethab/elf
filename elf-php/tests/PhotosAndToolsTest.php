<?php
declare(strict_types=1);

namespace Elf\Tests;

use Elf\Config;
use Elf\Tools\Client;
use Elf\Tools\SampleData;

/** Uploads and the media access rule; the sample builder; the command-line tool. */
final class PhotosAndToolsTest extends TestCase
{
    private function tmpFile(string $data): string
    {
        $p = tempnam(sys_get_temp_dir(), 'elfup');
        file_put_contents($p, $data);
        return $p;
    }

    private function jpeg(int $w = 900, int $h = 600): string
    {
        $im = imagecreatetruecolor($w, $h);
        imagefilledrectangle($im, 0, 0, $w, $h, imagecolorallocate($im, 150, 110, 70));
        ob_start();
        imagejpeg($im, null, 80);
        return (string) ob_get_clean();
    }

    public function testUploadReviewPublishAndAccessRule(): void
    {
        $this->makeUser('photog');
        $ed = $this->makeUser('pe', ['editor']);
        $c = $this->client('photog');
        $c->post('/contribute/person', ['preferred_name' => 'Testperson Photo (FICTIONAL)', 'living_status' => 'deceased', 'action' => 'draft']);
        $sid = (int) $this->db->val('SELECT MAX(id) FROM submissions');
        $file = $this->tmpFile($this->jpeg());
        $meta = ['caption' => 'Synthetic colour block (FICTIONAL)', 'rights_status' => 'public_domain', 'rights_declared' => '1'];
        $r = $c->post("/dashboard/submissions/{$sid}/photos", $meta, ['photo' => [$file, 'block.jpg']]);
        $this->assertSame("/dashboard/submissions/{$sid}#photos", $r->get('Location'));
        $files = $this->db->all('SELECT file_role, storage_key, width, access_level FROM media_files ORDER BY id');
        $this->assertSame(['original', 'access_derivative', 'thumbnail'], array_column($files, 'file_role'));
        $this->assertSame([900, 900, 480], array_map('intval', array_column($files, 'width')));
        [$orig, $display, $thumb] = array_column($files, 'storage_key');
        $this->assertStatus(200, $c->get("/media/{$thumb}"), 'the contributor sees their own photo');
        $this->assertStatus(404, $this->get("/media/{$thumb}"), 'nobody else does before publication');

        // progress-bar uploads get JSON
        $bad = $this->tmpFile('not an image at all');
        $j = $c->post("/dashboard/submissions/{$sid}/photos", $meta, ['photo' => [$bad, 'x.jpg']], ['X-Upload-Progress' => '1']);
        $this->assertSame(400, $j->status);
        $this->assertArrayHasKey('errors', $j->getJson());
        $pdf = $this->tmpFile("%PDF-1.4\n1 0 obj << /Type /Catalog /OpenAction << /S /JavaScript /JS (app.alert(1)) >> >>\nendobj\n%%EOF");
        $this->assertSame(400, $c->post("/dashboard/submissions/{$sid}/photos", $meta, ['photo' => [$pdf, 'x.pdf']], ['X-Upload-Progress' => '1'])->status);

        $c->post("/dashboard/submissions/{$sid}/submit");
        $edc = $this->client('pe');
        $edc->post("/editor/submissions/{$sid}/transition", ['to' => 'under_review']);
        $pid = (int) $this->db->val('SELECT id FROM submission_photos WHERE submission_id=?', [$sid]);
        $edc->post("/editor/submissions/{$sid}/photos/{$pid}", ['decision' => 'accept', 'access' => 'public', 'rights_status' => 'public_domain']);
        $edc->post("/editor/submissions/{$sid}/transition", ['to' => 'approved']);
        $edc->post("/editor/submissions/{$sid}/transition", ['to' => 'published']);
        $this->assertSame('published', $this->db->val('SELECT status FROM submissions WHERE id=?', [$sid]));

        $this->assertStatus(200, $this->get("/media/{$thumb}"));
        $this->assertStatus(200, $this->get("/media/{$display}"));
        $this->assertStatus(404, $this->get("/media/{$orig}"), 'the original stays with the editors');
        $slug = $this->db->val("SELECT slug FROM entities WHERE kind='person'");
        $page = $this->get("/people/{$slug}")->data();
        $this->assertStringContainsString("/media/{$display}", $page);                // the portrait is the display copy
        $this->assertStringNotContainsString($orig, $page);
        $this->assertStatus(404, $this->get('/media/no-such-key'));
        foreach ([$file, $bad, $pdf] as $p) {
            @unlink($p);
        }
    }

    public function testSampleArchiveIsSeparateFictionalAndComplete(): void
    {
        $dir = sys_get_temp_dir() . '/elf-sample-test-' . bin2hex(random_bytes(4));
        mkdir($dir);
        try {
            try {
                SampleData::build("{$dir}/real.db", "{$dir}/m", "{$dir}/real.db");
                $this->fail('the sample was allowed into the real database');
            } catch (\RuntimeException $e) {
                $this->assertStringContainsString('its own database', $e->getMessage());
            }
            [$password, $report] = SampleData::build("{$dir}/sample.db", "{$dir}/media", "{$dir}/real.db");
            $this->assertStringStartsWith('sample-', $password);
            $this->assertStringContainsString('12 place, 18 event, 11 person', $report[0]);
            $db = new \Elf\Db("{$dir}/sample.db");
            $this->assertSame(0, (int) $db->val('SELECT COUNT(*) FROM entities WHERE is_fictional_test=0'));
            $this->assertSame(0, (int) $db->val('SELECT COUNT(*) FROM events WHERE CAST(substr(date_start,1,4) AS INTEGER) < 2040'));
            $states = $db->col('SELECT DISTINCT status FROM submissions');
            foreach (['draft', 'submitted', 'under_review', 'needs_revision', 'published'] as $s) {
                $this->assertContains($s, $states);
            }
            $this->assertSame(2, (int) $db->val('SELECT COUNT(*) FROM explorations WHERE is_published=1'));
            $this->assertSame(1, (int) $db->val('SELECT COUNT(*) FROM reports'));
            // every staff record page opens (regression: archive items and collections failed in both editions)
            $app = new \Elf\App(['ENV' => 'testing', 'DATABASE_PATH' => "{$dir}/sample.db", 'MEDIA_ROOT' => "{$dir}/media",
                'SECRET_KEY' => str_repeat('s', 40), 'AUTO_MIGRATE' => false], []);
            $ed = new Client($app, 'sample_editor', $password);
            foreach ($db->all('SELECT kind, public_id FROM entities WHERE merged_into IS NULL AND deleted_at IS NULL') as $e) {
                $this->assertSame(200, $ed->get("/editor/records/{$e['public_id']}")->status, $e['kind']);
            }
            $this->assertSame(200, (new Client($app))->get('/explore')->status);
            $db = $ed = $app = null;                   // close the database files (Windows cannot delete open files)
        } finally {
            \Elf\App::$current = null;
            gc_collect_cycles();
            self::rmtree($dir);
        }
    }

    public function testCommandLineTool(): void
    {
        $dir = sys_get_temp_dir() . '/elf-cli-test-' . bin2hex(random_bytes(4));
        mkdir($dir);
        $php = escapeshellarg(PHP_BINARY);
        $elf = escapeshellarg(Config::root() . '/bin/elf');
        $env = ['ELF_ENV' => 'development', 'ELF_DATABASE_PATH' => "{$dir}/cli.db", 'ELF_MEDIA_ROOT' => "{$dir}/media"];
        $run = function (string $args) use ($php, $elf, $env): array {
            $p = proc_open("{$php} {$elf} {$args}", [1 => ['pipe', 'w'], 2 => ['pipe', 'w']], $pipes, null, $env + getenv());
            $out = stream_get_contents($pipes[1]) . stream_get_contents($pipes[2]);
            return [proc_close($p), $out];
        };
        try {
            [$code, $out] = $run('migrate');
            $this->assertSame(0, $code, $out);
            $this->assertStringContainsString('Applied: 0001', $out);
            $this->assertStringContainsString('already up to date', $run('migrate')[1]);
            [$code, $out] = $run('seed-test-data');
            $this->assertSame(0, $code, $out);
            $this->assertStringContainsString('Password for all dev accounts', $out);
            $this->assertStringContainsString('already present', $run('seed-test-data')[1]);
            [$code, $out] = $run('reindex');
            $this->assertSame(0, $code, $out);
            [$code, $out] = $run(escapeshellarg("{$dir}/backup.db") . ' --media ' . escapeshellarg("{$dir}/media-copy"));
            $this->assertSame(1, $code, 'a command name is required');
            [$code, $out] = $run('backup ' . escapeshellarg("{$dir}/backup.db"));
            $this->assertSame(0, $code, $out);
            $this->assertStringContainsString('integrity ok', $out);
            $this->assertSame(1, $run('backup ' . escapeshellarg("{$dir}/backup.db"))[0], 'never overwrites');
            [$code, $out] = $run('export-public ' . escapeshellarg("{$dir}/export.zip") . ' --include-fictional');
            $this->assertSame(0, $code, $out);
            $zip = new \ZipArchive();
            $this->assertTrue($zip->open("{$dir}/export.zip"));
            $this->assertNotFalse($zip->locateName('manifest.json'));
            $zip->close();
            [$code, $out] = $run('legacy-password-resets');
            $this->assertSame(0, $code, $out);
            $this->assertStringContainsString('Nothing to do', $out);
            $this->assertSame(1, $run('send-email')[0], 'needs SMTP settings');
        } finally {
            self::rmtree($dir);
        }
    }
}
