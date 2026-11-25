<?php
declare(strict_types=1);

namespace Elf\Services;

use Elf\Db;

/**
 * Spreadsheet (CSV) import with preview.
 *
 * 1. An editor uploads a CSV for one kind of record. Nothing is created yet.
 * 2. Every row is validated with exactly the same rules as the contribution forms. The preview shows each row's
 *    errors, possible duplicates already in the archive, and repeated rows within the file.
 * 3. On confirmation, each valid row becomes a normal SUBMITTED contribution (tagged with the batch), so imported
 *    records still go through editorial review before anything is public. Invalid rows are skipped and listed.
 *
 * Columns are the field names of the contribution form (a template can be downloaded). Inside a cell, several aliases
 * are separated by ";" and several sources by "||" (each source is "Title | page or locator | URL").
 */
final class Importer
{
    public const IMPORT_KINDS = ['person', 'family', 'place', 'event', 'organization', 'source',
        'relationship', 'affiliation', 'membership', 'participation'];
    public const MAX_ROWS = 2000;
    public const MAX_BYTES = 5 * 1024 * 1024;
    public const EXTRA_COLUMNS = ['contributor_note'];

    public static function columns(string $kind): array
    {
        return array_merge(array_map(fn ($f) => $f->name, Records::specFor($kind)), self::EXTRA_COLUMNS);
    }

    public static function templateCsv(string $kind): string
    {
        return "\u{FEFF}" . Csv::write([self::columns($kind)]);     // BOM so spreadsheet programs open it as UTF-8 (Ge'ez, Arabic)
    }

    private static function cellToForm(Field $f, ?string $value): string
    {
        $v = trim((string) $value);
        $split = fn (string $sep) => implode("\n", array_values(array_filter(array_map('trim',
            explode("\n", str_replace($sep, "\n", str_replace("\r", '', $v)))), fn ($x) => $x !== '')));
        return match ($f->kind) {
            'lines' => $split(';'),
            'sources' => $split('||'),
            default => $v,
        };
    }

    public static function parse(Db $db, string $kind, ?string $data, ?string $filename = null): array
    {
        if (!in_array($kind, self::IMPORT_KINDS, true)) {
            throw new ImportError('This kind of record cannot be imported.');
        }
        if ($data === null || $data === '') {
            throw new ImportError('Choose a CSV file to import.');
        }
        if (strlen($data) > self::MAX_BYTES) {
            throw new ImportError('The file is too large (the limit is 5 MB). Split it into smaller files.');
        }
        if (!mb_check_encoding($data, 'UTF-8')) {
            throw new ImportError('The file is not UTF-8 text. In your spreadsheet program, save it as “CSV UTF-8”.');
        }
        if (str_starts_with($data, "\u{FEFF}")) {
            $data = substr($data, 3);
        }
        $all = Csv::read($data);
        $headerRow = array_shift($all) ?? [];
        $header = array_map('trim', $headerRow);
        $known = self::columns($kind);
        $unknown = array_values(array_filter($header, fn ($h) => $h !== '' && !in_array($h, $known, true)));
        $spec = Records::specFor($kind);
        $missing = [];
        foreach ($spec as $f) {
            if ($f->required && !in_array($f->name, $header, true)) {
                $missing[] = $f->name;
            }
        }
        if (!array_filter($header, fn ($h) => $h !== '')) {
            throw new ImportError('The file has no header row.');
        }
        if ($unknown || $missing) {
            $parts = [];
            if ($unknown) {
                $parts[] = 'Unknown columns: ' . implode(', ', $unknown);
            }
            if ($missing) {
                $parts[] = 'Missing required columns: ' . implode(', ', $missing);
            }
            throw new ImportError(implode('. ', $parts) . '. Download the template to see the expected columns.');
        }
        $rows = [];
        $seen = [];
        $titleField = Records::TITLE_FIELD[$kind] ?? null;
        $line = 1;                                      // line 1 is the header; empty lines are not counted (as Python's reader)
        foreach ($all as $cells) {
            if (!$cells) {
                continue;
            }
            $line++;
            if ($line - 1 > self::MAX_ROWS) {
                throw new ImportError('The file has more than ' . self::MAX_ROWS . ' rows. Split it into smaller files.');
            }
            $raw = [];
            foreach ($header as $i => $h) {
                $raw[$h] = $cells[$i] ?? null;
            }
            $nonEmpty = array_filter($raw, fn ($v) => is_string($v) && trim($v) !== '');
            if (!$nonEmpty) {
                continue;                               // blank line
            }
            $form = [];
            foreach ($spec as $f) {
                $form[$f->name] = self::cellToForm($f, $raw[$f->name] ?? null);
            }
            [$clean, $errors] = Records::validate($db, $kind, $form);
            $warnings = [];
            if (!$errors && $titleField) {
                $key = Names::normalize($clean[$titleField]);
                if (isset($seen[$key])) {
                    $warnings[] = "Same name as line {$seen[$key]} in this file.";
                }
                $seen[$key] ??= $line;
            }
            if (!$errors && $kind === 'person') {
                $names = array_merge([$clean['preferred_name'] ?? null, $clean['full_name'] ?? null], $clean['aliases'] ?? []);
                $by = ($clean['birth'] ?? [])['start'] ?? null;
                foreach (Duplicates::findPersonCandidates($db, $names, $by ? substr($by, 0, 4) : null, 3) as $c) {
                    $warnings[] = "Possible duplicate of {$c['name']} ({$c['public_id']}): {$c['why']}.";
                }
            }
            $rows[] = ['line' => $line, 'form' => array_filter($form, fn ($v) => $v !== ''), 'data' => $errors ? null : $clean,
                'errors' => $errors, 'warnings' => $warnings, 'note' => mb_substr(trim((string) ($raw['contributor_note'] ?? '')), 0, 3000)];
        }
        if (!$rows) {
            throw new ImportError('The file has no data rows.');
        }
        return $rows;
    }

    public static function createPreview(Db $db, CurrentUser $user, string $kind, ?string $data, ?string $filename): int
    {
        $rows = self::parse($db, $kind, $data, $filename);
        $valid = count(array_filter($rows, fn ($r) => $r['data'] !== null));
        return $db->tx(fn () => $db->insert('INSERT INTO imports(kind, filename, created_by, rows_json, total_rows, valid_rows) VALUES (?,?,?,?,?,?)',
            [$kind, mb_substr((string) $filename, 0, 200) ?: null, $user->id, Util::json(self::jsonRows($rows)), count($rows), $valid]));
    }

    /** Empty error maps are stored as JSON objects, as the Python edition writes them. */
    private static function jsonRows(array $rows): array
    {
        foreach ($rows as &$r) {
            if ($r['errors'] === []) {
                $r['errors'] = new \stdClass();
            }
            if ($r['form'] === []) {
                $r['form'] = new \stdClass();
            }
        }
        return $rows;
    }

    public static function get(Db $db, int $importId): array
    {
        $imp = $db->one('SELECT * FROM imports WHERE id=?', [$importId]);
        return $imp ? [$imp, json_decode((string) $imp['rows_json'], true) ?: []] : [null, null];
    }

    /** Turn every valid row into a submitted contribution for review. Returns how many were created. */
    public static function confirm(Db $db, CurrentUser $user, int $importId, array $config): int
    {
        [$imp, $rows] = self::get($db, $importId);
        if (!$imp || $imp['status'] !== 'preview') {
            throw new ImportError('This import has already been processed.');
        }
        if ($imp['created_by'] !== $user->id) {
            throw new ImportError('Only the editor who uploaded the file can confirm it.');
        }
        return $db->tx(function () use ($db, $user, $importId, $imp, $rows, $config) {
            $created = 0;
            foreach ($rows as $r) {
                if ($r['data'] === null) {
                    continue;
                }
                $note = trim('Imported from ' . ($imp['filename'] ?: 'a CSV file') . ", line {$r['line']}." . ($r['note'] ? " {$r['note']}" : ''));
                $sid = Workflow::create($db, $user, $imp['kind'], $r['data'], $config, null, null, $note, null, true, $importId);
                Workflow::transition($db, $user, $sid, 'submitted', $config);
                $created++;
            }
            $db->exec("UPDATE imports SET status='created' WHERE id=?", [$importId]);
            return $created;
        });
    }

    public static function discard(Db $db, CurrentUser $user, int $importId): void
    {
        [$imp] = self::get($db, $importId);
        if (!$imp || $imp['status'] !== 'preview') {
            throw new ImportError('This import has already been processed.');
        }
        $db->tx(fn () => $db->exec("UPDATE imports SET status='discarded', rows_json='[]' WHERE id=?", [$importId]));
    }

    /**
     * Move each selected submission through review → approval → publication. Each one is checked exactly as if done by
     * hand (permissions, own-work rule, references, photos). Returns [published, failures].
     */
    public static function bulkPublish(Db $db, CurrentUser $editor, array $sids, array $config): array
    {
        $published = 0;
        $failures = [];
        foreach ($sids as $sid) {
            $s = $db->one('SELECT * FROM submissions WHERE id=?', [$sid]);
            if (!$s) {
                continue;
            }
            try {
                $path = ['submitted' => ['under_review', 'approved', 'published'], 'under_review' => ['approved', 'published'],
                    'approved' => ['published']][$s['status']] ?? null;
                if (!$path) {
                    throw new WorkflowError("cannot be published from the state “{$s['status']}”.");
                }
                foreach ($path as $to) {
                    Workflow::transition($db, $editor, (int) $sid, $to, $config, $to === 'approved' ? 'Approved in a batch review.' : null);
                }
                $published++;
            } catch (WorkflowError|PermissionDenied $e) {
                $failures[] = [(int) $sid, Workflow::titleFor($db, $s), $e->getMessage()];
            }
        }
        return [$published, $failures];
    }
}
