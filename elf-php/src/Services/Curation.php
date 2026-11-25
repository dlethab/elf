<?php
declare(strict_types=1);

namespace Elf\Services;

use Elf\Db;
use Elf\Vocab;

/**
 * Editorial curation of published records: direct edits, claim-level citations, conflicting accounts, and the links
 * between records (relationships, memberships, affiliations, participation).
 *
 * Every change requires a reason (except adding new evidence), writes a revision on each affected record, and writes
 * an audit entry that keeps the PREVIOUS values, so nothing an editor changes or removes is lost from the history.
 */
final class Curation
{
    /** table => [entity columns, editable fields] */
    public const LINKS = [
        'relationships' => [['person_a_id', 'person_b_id'], ['status', 'visibility', 'notes', 'period']],
        'family_memberships' => [['family_id', 'person_id'], ['visibility', 'role_note', 'period']],
        'affiliations' => [['person_id', 'organization_id'], ['evidence_status', 'visibility', 'role', 'notes', 'period']],
        'event_participants' => [['event_id', 'person_id', 'organization_id'], ['evidence_status', 'role', 'notes']],
    ];

    private static function reason(array $form, bool $required = true): ?string
    {
        $r = mb_substr(Util::squash($form['reason'] ?? ''), 0, 1000);
        if ($required && $r === '') {
            throw new CurationError('Please record a reason. It is kept in the audit log.');
        }
        return $r !== '' ? $r : null;
    }

    private static function text(array $form, string $name, int $limit, bool $multiline = false): ?string
    {
        $v = str_replace("\r\n", "\n", (string) ($form[$name] ?? ''));
        $v = $multiline ? trim($v) : Util::squash($v);
        $v = mb_substr($v, 0, $limit);
        return $v !== '' ? $v : null;
    }

    // ───────────── direct edits by editors ─────────────
    /** Apply an editor's edit immediately (no second review), with a reason. Returns [changes|null, errors]. */
    public static function directEdit(Db $db, CurrentUser $editor, array $entity, array $form): array
    {
        $kind = $entity['kind'];
        if (!in_array($kind, Records::CORRECTABLE_KINDS, true)) {
            throw new CurationError('This kind of record cannot be edited here.');
        }
        $reason = self::reason($form);
        [$clean, $errors] = Records::validate($db, $kind, $form, false);
        if ($errors) {
            return [null, $errors];
        }
        $changes = Records::changedFields($db, $kind, (int) $entity['id'], $clean);
        if (!$changes) {
            return [null, ['form' => 'Nothing was changed.']];
        }
        Records::applyCorrection($db, $entity, $changes, $editor->id, null, $reason, 'Edited by an editor');
        return [$changes, []];
    }

    // ───────────── citations ─────────────
    /** Which claims a citation can support on this kind of record. */
    public static function citationFields(string $kind): array
    {
        $out = [['', 'General (the record as a whole)']];
        // archive items and collections have no record form: a citation supports the record as a whole
        $fields = in_array($kind, Specs::kinds(), true) ? Records::specFor($kind, false) : [];
        foreach ($fields as $f) {
            if (!in_array($f->kind, ['lines', 'refs', 'consents'], true)) {
                $out[] = [$f->name, $f->label];
            }
        }
        $extra = ['relationship' => ['person'], 'affiliation' => ['person'], 'members' => ['family'], 'participants' => ['event']];
        foreach ($extra as $n => $kinds) {
            if (in_array($kind, $kinds, true)) {
                $out[] = [$n, ucfirst($n)];
            }
        }
        return $out;
    }

    private static function citationValues(string $kind, array $form): array
    {
        $field = (string) ($form['field_name'] ?? '');
        if (!in_array($field, array_column(self::citationFields($kind), 0), true)) {
            throw new CurationError('Choose one of the listed options.');
        }
        $ev = ($form['evidence_status'] ?? '') ?: 'unverified';
        if (!isset(Vocab::EVIDENCE[$ev])) {
            throw new CurationError('Choose one of the listed options.');
        }
        return ['field_name' => $field !== '' ? $field : null, 'claim_text' => self::text($form, 'claim_text', 1000),
            'locator' => self::text($form, 'locator', 200), 'explanation' => self::text($form, 'explanation', 2000, true),
            'evidence_status' => $ev, 'editor_note' => self::text($form, 'editor_note', 2000, true)];
    }

    public static function addCitation(Db $db, CurrentUser $editor, array $entity, array $form): int
    {
        [$srcPid, $err] = Records::parseRef($db, $form['source'] ?? null, 'source');
        if ($err || !$srcPid) {
            throw new CurationError($err ?: 'Choose a source.');
        }
        $src = Entities::getByPublicId($db, $srcPid);
        $vals = self::citationValues($entity['kind'], $form);
        $cid = $db->insert('INSERT INTO citations(source_id, target_id, field_name, claim_text, locator, explanation, evidence_status, '
            . 'editor_note, created_by) VALUES (?,?,?,?,?,?,?,?,?)',
            [$src['id'], $entity['id'], $vals['field_name'], $vals['claim_text'], $vals['locator'], $vals['explanation'],
                $vals['evidence_status'], $vals['editor_note'], $editor->id]);
        Entities::addRevision($db, (int) $entity['id'], $editor->id, 'Citation added: ' . Entities::titleOf($db, (int) $src['id'])
            . ' (' . Vocab::EVIDENCE[$vals['evidence_status']][0] . ')');
        Audit::log($db, $editor->id, 'citation.added', $entity['kind'], $entity['public_id'], ['citation' => $cid] + $vals);
        return $cid;
    }

    private static function citation(Db $db, array $entity, int $cid): array
    {
        $c = $db->one('SELECT * FROM citations WHERE id=? AND target_id=?', [$cid, $entity['id']]);
        if (!$c) {
            throw new CurationError('Citation not found.');
        }
        return $c;
    }

    public static function updateCitation(Db $db, CurrentUser $editor, array $entity, int $cid, array $form): void
    {
        $old = self::citation($db, $entity, $cid);
        $vals = self::citationValues($entity['kind'], $form);
        $reason = self::reason($form, false);
        $db->exec('UPDATE citations SET field_name=?, claim_text=?, locator=?, explanation=?, evidence_status=?, editor_note=? WHERE id=?',
            [...array_values($vals), $cid]);
        $title = Entities::titleOf($db, (int) $old['source_id']);
        Entities::addRevision($db, (int) $entity['id'], $editor->id, "Citation assessed: {$title} — " . Vocab::EVIDENCE[$vals['evidence_status']][0], $reason);
        Audit::log($db, $editor->id, 'citation.updated', $entity['kind'], $entity['public_id'],
            ['citation' => $cid, 'before' => array_intersect_key($old, $vals), 'after' => $vals, 'reason' => $reason]);
    }

    public static function removeCitation(Db $db, CurrentUser $editor, array $entity, int $cid, array $form): void
    {
        $old = self::citation($db, $entity, $cid);
        $reason = self::reason($form);
        $db->exec('DELETE FROM citations WHERE id=?', [$cid]);
        Entities::addRevision($db, (int) $entity['id'], $editor->id, 'Citation removed: ' . Entities::titleOf($db, (int) $old['source_id']), $reason);
        Audit::log($db, $editor->id, 'citation.removed', $entity['kind'], $entity['public_id'], ['removed' => $old, 'reason' => $reason]);
    }

    // ───────────── conflicting accounts ─────────────
    private static function accountValues(Db $db, array $form): array
    {
        $topic = self::text($form, 'topic', 200);
        $text = self::text($form, 'account_text', 5000, true);
        if (!$topic || !$text) {
            throw new CurationError('Give the topic and the account.');
        }
        $srcId = null;
        if (trim((string) ($form['source'] ?? '')) !== '') {
            [$pid, $err] = Records::parseRef($db, $form['source'], 'source');
            if ($err) {
                throw new CurationError($err);
            }
            $srcId = (int) Entities::getByPublicId($db, $pid)['id'];
        }
        return ['topic' => $topic, 'account_text' => $text, 'attributed_to' => self::text($form, 'attributed_to', 300), 'source_id' => $srcId,
            'basis_note' => self::text($form, 'basis_note', 2000, true), 'needs_research' => (int) (($form['needs_research'] ?? null) === '1'),
            'is_public' => (int) (($form['is_public'] ?? null) === '1'), 'concerns_date' => (int) (($form['concerns_date'] ?? null) === '1'),
            'concerns_location' => (int) (($form['concerns_location'] ?? null) === '1')];
    }

    public static function addAccount(Db $db, CurrentUser $editor, array $entity, array $form): int
    {
        $vals = self::accountValues($db, $form);
        $aid = $db->insert('INSERT INTO conflicting_accounts(entity_id, ' . implode(', ', array_keys($vals)) . ', created_by) VALUES (?,'
            . implode(',', array_fill(0, count($vals), '?')) . ',?)', [$entity['id'], ...array_values($vals), $editor->id]);
        Entities::addRevision($db, (int) $entity['id'], $editor->id, 'Differing account recorded');
        Audit::log($db, $editor->id, 'account.added', $entity['kind'], $entity['public_id'], ['account' => $aid] + $vals);
        return $aid;
    }

    public static function updateAccount(Db $db, CurrentUser $editor, array $entity, int $aid, array $form): void
    {
        $old = $db->one('SELECT * FROM conflicting_accounts WHERE id=? AND entity_id=?', [$aid, $entity['id']]);
        if (!$old) {
            throw new CurationError('Account not found.');
        }
        $reason = self::reason($form);
        $vals = self::accountValues($db, $form);
        $db->exec('UPDATE conflicting_accounts SET ' . implode(', ', array_map(fn ($k) => "{$k}=?", array_keys($vals))) . ', updated_at=?, updated_by=? WHERE id=?',
            [...array_values($vals), Util::nowIso(), $editor->id, $aid]);
        Entities::addRevision($db, (int) $entity['id'], $editor->id, 'Differing account revised', $reason);
        Audit::log($db, $editor->id, 'account.updated', $entity['kind'], $entity['public_id'],
            ['account' => $aid, 'before' => array_intersect_key($old, $vals), 'after' => $vals, 'reason' => $reason]);
    }

    // ───────────── links between records ─────────────
    private static function link(Db $db, string $table, int $linkId): array
    {
        if (!isset(self::LINKS[$table])) {
            throw new CurationError('Unknown link.');
        }
        $row = $db->one("SELECT * FROM {$table} WHERE id=?", [$linkId]);
        if (!$row) {
            throw new CurationError('Link not found.');
        }
        return $row;
    }

    public static function linkEntities(array $row, string $table): array
    {
        $out = [];
        foreach (self::LINKS[$table][0] as $c) {
            if ($row[$c] !== null) {
                $out[] = (int) $row[$c];
            }
        }
        return $out;
    }

    public static function updateLink(Db $db, CurrentUser $editor, string $table, int $linkId, array $form): void
    {
        $old = self::link($db, $table, $linkId);
        $reason = self::reason($form);
        $sets = [];
        foreach (self::LINKS[$table][1] as $f) {
            if ($f === 'period') {
                try {
                    $sets += Dates::columns('period', Dates::parse($form['period'] ?? ''));
                } catch (DateError $e) {
                    throw new CurationError($e->getMessage(), 0, $e);
                }
            } elseif ($f === 'status') {
                if (!in_array($form['status'] ?? null, Vocab::RELATIONSHIP_STATUSES, true)) {
                    throw new CurationError('Choose one of the listed options.');
                }
                $sets['status'] = $form['status'];
            } elseif ($f === 'visibility') {
                if (!in_array($form['visibility'] ?? null, Vocab::VISIBILITIES, true)) {
                    throw new CurationError('Choose one of the listed options.');
                }
                $sets['visibility'] = $form['visibility'];
            } elseif ($f === 'evidence_status') {
                if (!isset(Vocab::EVIDENCE[$form['evidence_status'] ?? ''])) {
                    throw new CurationError('Choose one of the listed options.');
                }
                $sets['evidence_status'] = $form['evidence_status'];
            } else {
                $sets[$f] = self::text($form, $f, 2000, $f === 'notes');
            }
        }
        if (($sets['visibility'] ?? null) === 'public') {
            foreach (self::linkEntities($old, $table) as $eid) {
                $e = Entities::get($db, $eid);
                if ($e['kind'] === 'person' && (Entities::subtypeRow($db, $eid)['living_status'] ?? null) === 'living' && ($form['consent_confirmed'] ?? null) !== '1') {
                    throw new CurationError('This link involves a person recorded as living. Confirm that consent to publish has been obtained.');
                }
            }
        }
        $db->exec("UPDATE {$table} SET " . implode(', ', array_map(fn ($k) => "{$k}=?", array_keys($sets))) . ' WHERE id=?', [...array_values($sets), $linkId]);
        foreach (self::linkEntities($old, $table) as $eid) {
            Entities::addRevision($db, $eid, $editor->id, 'Link revised (' . str_replace('_', ' ', $table) . ')', $reason);
        }
        Audit::log($db, $editor->id, 'link.updated', $table, $linkId, ['before' => array_intersect_key($old, $sets), 'after' => $sets, 'reason' => $reason]);
    }

    public static function removeLink(Db $db, CurrentUser $editor, string $table, int $linkId, array $form): void
    {
        $old = self::link($db, $table, $linkId);
        $reason = self::reason($form);
        $db->exec("DELETE FROM {$table} WHERE id=?", [$linkId]);
        foreach (self::linkEntities($old, $table) as $eid) {
            Entities::addRevision($db, $eid, $editor->id, 'Link removed (' . str_replace('_', ' ', $table) . ')', $reason);
        }
        Audit::log($db, $editor->id, 'link.removed', $table, $linkId, ['removed' => $old, 'reason' => $reason]);
    }

    /** Every link touching a record, for the staff view (including restricted ones). */
    public static function linksFor(Db $db, array $entity): array
    {
        $eid = (int) $entity['id'];
        $out = [];
        $name = function ($i) use ($db) {
            $e = Entities::get($db, (int) $i);
            return $e ? ['id' => $e['public_id'], 'kind' => $e['kind'], 'title' => Entities::titleOf($db, (int) $i)] : null;
        };
        foreach (self::LINKS as $table => [$cols]) {
            $where = implode(' OR ', array_map(fn ($c) => "{$c}=?", $cols));
            foreach ($db->all("SELECT * FROM {$table} WHERE {$where} ORDER BY id", array_fill(0, count($cols), $eid)) as $r) {
                $others = [];
                foreach ($cols as $c) {
                    if ($r[$c] !== null && $r[$c] !== $eid) {
                        $o = $name($r[$c]);
                        if ($o) {
                            $others[] = $o;
                        }
                    }
                }
                $hasPeriod = array_key_exists('period_start', $r);
                $out[] = ['table' => $table, 'row' => $r, 'others' => $others,
                    'period' => $hasPeriod ? Dates::format($r['period_start'], $r['period_end'], $r['period_precision']) : null,
                    'period_input' => $hasPeriod ? Dates::toInput($r['period_start'], $r['period_end'], $r['period_precision']) : null];
            }
        }
        return $out;
    }
}
