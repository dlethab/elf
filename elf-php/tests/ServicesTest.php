<?php
declare(strict_types=1);

namespace Elf\Tests;

use Elf\Services\Dates;
use Elf\Services\Entities;
use Elf\Services\Names;
use Elf\Services\PermissionDenied;
use Elf\Services\Records;
use Elf\Services\Search;
use Elf\Services\SequenceMatcher;
use Elf\Services\Workflow;
use Elf\Services\WorkflowError;

/** Validation, dates, names and the workflow rules, called directly (the same rules the pages use). */
final class ServicesTest extends TestCase
{
    public function testUncertaintyIsPreservedAndInvalidDatesRejected(): void
    {
        $d = Dates::parse('c. 1952');
        $this->assertSame(['1952', null, 'approximate'], [$d->start, $d->end, $d->precision]);   // as stored by the Python edition
        $this->assertSame('decade', Dates::parse('1950s')->precision);
        $this->assertSame('range', Dates::parse('1950 to 1955')->precision);
        $this->assertSame('month', Dates::parse('1952-03')->precision);
        $this->assertSame('unknown', Dates::parse('')->precision);
        foreach (['1952-13', '1952-02-30', 'soon', '0999', '1955 to 1950'] as $bad) {
            try {
                Dates::parse($bad);
                $this->fail("accepted {$bad}");
            } catch (\Elf\Services\DateError) {
                $this->addToAssertionCount(1);
            }
        }
        // round trip through the form
        $this->assertSame('c. 1952', Dates::toInput($d->start, $d->end, $d->precision));
    }

    public function testNameNormalisationKeepsScripts(): void
    {
        $this->assertSame(Names::normalize('Ḥamid  Idris'), Names::normalize('hamid idris'));
        $this->assertNotSame('', Names::normalize('ሓሚድ እድሪስ'));                 // Ge'ez script kept
        $this->assertNotSame('', Names::normalize('حامد إدريس'));
        $this->assertNotSame('', Names::slugify('ሓሚድ', 'per-abc12345'));
    }

    public function testCoordinatesNeedBothValuesAndAPrecision(): void
    {
        [, $e1] = Records::validate($this->db, 'place', ['primary_name' => 'Testville (FICTIONAL)', 'latitude' => '15.3']);
        $this->assertArrayHasKey('longitude', $e1 + $this->errorsFor($e1, 'latitude'));
        [, $e2] = Records::validate($this->db, 'place', ['primary_name' => 'Testville (FICTIONAL)', 'latitude' => '15.3', 'longitude' => '38.9']);
        $this->assertArrayHasKey('coord_precision', $e2);
        [, $e3] = Records::validate($this->db, 'place', ['primary_name' => 'Testville (FICTIONAL)', 'latitude' => '95', 'longitude' => '38.9',
            'coord_precision' => 'exact']);
        $this->assertNotEmpty($e3);
    }

    private function errorsFor(array $errors, string $alt): array
    {
        return isset($errors[$alt]) ? ['longitude' => $errors[$alt]] : [];
    }

    public function testNothingExistsUntilPublishedAndStatesCannotBeSkipped(): void
    {
        $c = $this->makeUser('c');
        $ed = $this->makeUser('e', ['editor']);
        $mod = $this->makeUser('m', ['moderator']);
        $sid = $this->submitNew($c, 'person', ['preferred_name' => 'Testperson Rules (FICTIONAL)', 'living_status' => 'deceased']);
        $this->assertSame(0, (int) $this->db->val("SELECT COUNT(*) FROM entities WHERE kind='person'"));
        foreach ([[$c, 'under_review'], [$mod, 'under_review']] as [$who, $to]) {
            try {
                Workflow::transition($this->db, $who, $sid, $to, self::CONFIG);
                $this->fail('transition allowed');
            } catch (PermissionDenied) {
                $this->addToAssertionCount(1);
            }
        }
        try {
            Workflow::transition($this->db, $ed, $sid, 'published', self::CONFIG);   // submitted → published skips review
            $this->fail('state skipped');
        } catch (WorkflowError|PermissionDenied) {
            $this->addToAssertionCount(1);
        }
        Workflow::transition($this->db, $ed, $sid, 'under_review', self::CONFIG);
        try {
            Workflow::transition($this->db, $ed, $sid, 'rejected', self::CONFIG);    // a reason is required
            $this->fail('rejected without a reason');
        } catch (WorkflowError) {
            $this->addToAssertionCount(1);
        }
        Workflow::transition($this->db, $ed, $sid, 'approved', self::CONFIG);
        $s = Workflow::transition($this->db, $ed, $sid, 'published', self::CONFIG);
        $e = Entities::get($this->db, (int) $s['result_entity_id']);
        $this->assertSame('published', $e['publication_status']);
        $this->assertGreaterThan(0, (int) $this->db->val('SELECT COUNT(*) FROM revisions WHERE entity_id=?', [$e['id']]));
        $this->assertSame([$e['public_id']], array_column(Search::search($this->db, 'Rules')['results'], 'public_id'));
    }

    public function testAuditAndRevisionsAreAppendOnly(): void
    {
        $this->db->exec("INSERT INTO audit_logs(action) VALUES ('test.event')");
        foreach (['UPDATE audit_logs SET action=\'x\'', 'DELETE FROM audit_logs'] as $sql) {
            try {
                $this->db->exec($sql);
                $this->fail("allowed: {$sql}");
            } catch (\PDOException) {
                $this->addToAssertionCount(1);
            }
        }
    }

    public function testLivingPersonIsRestrictedUntilConsent(): void
    {
        $c = $this->makeUser('c');
        $ed = $this->makeUser('e', ['editor']);
        $p = $this->publishNew($c, $ed, 'person', ['preferred_name' => 'Testperson Alive (FICTIONAL)', 'living_status' => 'living']);
        $this->assertSame('restricted', $p['visibility']);
        $this->assertSame([], Search::search($this->db, 'Alive')['results']);
        $q = $this->publishNew($c, $ed, 'person', ['preferred_name' => 'Testperson Consented (FICTIONAL)', 'living_status' => 'living'], true);
        $this->assertSame('public', $q['visibility']);
    }

    public function testSimilarNamesAreCandidatesNotMerges(): void
    {
        $c = $this->makeUser('c');
        $ed = $this->makeUser('e', ['editor']);
        $this->publishNew($c, $ed, 'person', ['preferred_name' => 'Testperson Abraha (FICTIONAL)', 'living_status' => 'deceased']);
        $cands = \Elf\Services\Duplicates::findPersonCandidates($this->db, ['Testperson Abreha (FICTIONAL)']);
        $this->assertCount(1, $cands);
        $this->assertSame(1, (int) $this->db->val("SELECT COUNT(*) FROM entities WHERE kind='person'"));
    }

    public function testSequenceMatcherAgreesWithPython(): void
    {
        // difflib.SequenceMatcher(None, a, b).ratio() values computed with CPython
        $this->assertEqualsWithDelta(0.8, (new SequenceMatcher('abcde', 'abxde'))->ratio(), 1e-9);
        $this->assertEqualsWithDelta(0.6, (new SequenceMatcher('tesfay', 'tesfai'))->ratio() - 0.2333333333333333, 1e-9);
        $this->assertSame(['tesfay'], Search::closeMatches('tesfai', ['tesfay', 'asmara', 'keren']));
    }

    public function testFloatsArePrintedAsPythonPrintsThem(): void
    {
        $this->assertSame('15.0', Records::floatRepr(15.0));
        $this->assertSame('15.62', Records::floatRepr(15.62));
        $this->assertSame('0.1', Records::floatRepr(0.1));
        $this->assertSame('1e-05', Records::floatRepr(0.00001));
        $this->assertSame('0.0001', Records::floatRepr(0.0001));
        $this->assertSame('1e+16', Records::floatRepr(1e16));
        $this->assertSame('1000000000000000.0', Records::floatRepr(1e15));
        $this->assertSame('1.2345678901234568e+17', Records::floatRepr(123456789012345678.0));
        $this->assertSame('-2.5e-07', Records::floatRepr(-2.5e-7));
        $this->assertSame('0.30000000000000004', Records::floatRepr(0.1 + 0.2));
        $this->assertSame('-0.0', Records::floatRepr(-0.0));
    }
}
