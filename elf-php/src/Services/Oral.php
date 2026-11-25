<?php
declare(strict_types=1);

namespace Elf\Services;

use Elf\Db;
use Elf\Vocab;

/**
 * Oral histories and consent.
 *
 * Consent is recorded per use (record, store, publish the recording, publish the transcript, publish a translation,
 * quote excerpts, research access, download). Each public element of an interview is shown only if ITS consent is on
 * record and not revoked, and nothing is shown while an embargo is in force. "Uploaded" never means "published": a
 * contributor's declaration of consent becomes a consent record only when an editor confirms, at publication, that
 * they have seen evidence of it.
 *
 * This class is the single place that answers "may this part of this interview be shown?".
 */
final class Oral
{
    /** {consent_type: row or null} for the active (unrevoked) consent records. */
    public static function consents(Db $db, int $ohId): array
    {
        $rows = [];
        foreach ($db->all('SELECT c.*, u.username AS recorded_by_name FROM consent_records c LEFT JOIN users u ON u.id=c.recorded_by '
            . 'WHERE c.oral_history_id=? AND c.revoked_at IS NULL', [$ohId]) as $r) {
            $rows[$r['consent_type']] = $r;
        }
        $out = [];
        foreach (Vocab::CONSENT_TYPES as $t) {
            $out[$t] = $rows[$t] ?? null;
        }
        return $out;
    }

    public static function embargoed(array $oh): bool
    {
        return (bool) $oh['embargo_until'] && $oh['embargo_until'] > gmdate('Y-m-d');
    }

    /** What may be shown publicly, as an array of booleans. Embargo overrides everything. */
    public static function allowed(Db $db, int $ohId): array
    {
        $oh = $db->one('SELECT * FROM oral_histories WHERE entity_id=?', [$ohId]);
        $c = self::consents($db, $ohId);
        $ok = [];
        foreach (Vocab::CONSENT_TYPES as $t) {
            $ok[$t] = (bool) ($c[$t] && $c[$t]['granted']);
        }
        $emb = self::embargoed($oh);
        if ($emb) {
            $research = $ok['research_access'];
            $ok = array_fill_keys(array_keys($ok), false);
            $ok['research_access'] = $research;
        }
        $ok['embargoed'] = $emb;
        return $ok;
    }

    public static function shouldBePublic(Db $db, int $ohId): bool
    {
        $a = self::allowed($db, $ohId);
        return $a['publish_recording'] || $a['publish_transcript'];
    }

    /** Bring the record's visibility, its recording and the search index into line with consent. */
    public static function sync(Db $db, int $ohId, ?int $actorId, ?string $reason): void
    {
        $e = Entities::get($db, $ohId);
        $want = self::shouldBePublic($db, $ohId) ? 'public' : 'restricted';
        if ($e['visibility'] !== $want && $e['visibility'] !== 'private') {
            Entities::setState($db, $ohId, null, $want, $actorId, $reason);
        }
        $oh = $db->one('SELECT media_item_id FROM oral_histories WHERE entity_id=?', [$ohId]);
        if ($oh['media_item_id']) {
            $item = Entities::get($db, (int) $oh['media_item_id']);
            $a = $db->one('SELECT rights_status FROM archive_items WHERE entity_id=?', [$item['id']]);
            $decision = $db->one('SELECT editor_access FROM submission_photos WHERE result_item_id=?', [$item['id']]);
            $recOk = self::allowed($db, $ohId)['publish_recording'] && in_array($a['rights_status'], Vocab::PUBLIC_RIGHTS, true)
                && ($decision === null || $decision['editor_access'] === 'public');     // consent never overrides an editor's "restricted"
            $wantItem = $recOk ? 'public' : 'restricted';
            if ($item['visibility'] !== $wantItem) {
                Entities::setState($db, (int) $item['id'], null, $wantItem, $actorId, $reason);
            }
            Photos::syncItemAccess($db, (int) $item['id']);
        }
        Search::reindex($db, $ohId);
    }

    /** At publication: link the records it concerns, and record consent only if an editor confirmed it. */
    public static function afterCreate(Db $db, int $ohId, array $clean, ?int $actorId, bool $consentConfirmed): void
    {
        foreach ($clean['related'] ?? [] as $pid) {
            $e = Entities::getByPublicId($db, $pid);
            if ($e) {
                $db->exec('INSERT OR IGNORE INTO oral_history_subjects(oral_history_id, subject_id) VALUES (?,?)', [$ohId, $e['id']]);
            }
        }
        if (!empty($clean['interviewee'])) {
            $e = Entities::getByPublicId($db, $clean['interviewee']);
            $db->exec('INSERT OR IGNORE INTO oral_history_subjects(oral_history_id, subject_id) VALUES (?,?)', [$ohId, $e['id']]);
        }
        $declared = ($clean['consents'] ?? [])['granted'] ?? [];
        if ($consentConfirmed) {
            $note = ($clean['consents'] ?? [])['note'] ?? null;
            foreach (Vocab::CONSENT_TYPES as $t) {
                $db->exec('INSERT INTO consent_records(oral_history_id, consent_type, granted, granted_on, granted_by_text, evidence_note, recorded_by) '
                    . 'VALUES (?,?,?,?,?,?,?)', [$ohId, $t, (int) in_array($t, $declared, true), null, 'Declared by the contributor',
                        trim('Confirmed by an editor at publication. ' . ($note ?? '')), $actorId]);
            }
        }
        Audit::log($db, $actorId, $consentConfirmed ? 'oral_history.consent_recorded' : 'oral_history.consent_not_confirmed',
            'oral_history', Entities::get($db, $ohId)['public_id'], ['declared' => $declared, 'confirmed' => $consentConfirmed]);
    }

    /** Grant or withdraw one kind of consent, with evidence. The previous record is kept (revoked, not deleted). */
    public static function setConsent(Db $db, CurrentUser $editor, int $ohId, string $consentType, array $form): void
    {
        if (!in_array($consentType, Vocab::CONSENT_TYPES, true)) {
            throw new ConsentError('Choose one of the listed options.');
        }
        $granted = ($form['granted'] ?? null) === '1';
        $evidence = mb_substr(Util::squash($form['evidence_note'] ?? ''), 0, 2000);
        if ($evidence === '') {
            throw new ConsentError('Record the evidence for this consent decision (for example: signed form dated …, kept in …).');
        }
        $on = substr(trim((string) ($form['granted_on'] ?? '')), 0, 10) ?: null;
        $by = mb_substr(Util::squash($form['granted_by_text'] ?? ''), 0, 200) ?: null;
        $db->exec('UPDATE consent_records SET revoked_at=? WHERE oral_history_id=? AND consent_type=? AND revoked_at IS NULL', [Util::nowIso(), $ohId, $consentType]);
        $db->exec('INSERT INTO consent_records(oral_history_id, consent_type, granted, granted_on, granted_by_text, evidence_note, recorded_by) '
            . 'VALUES (?,?,?,?,?,?,?)', [$ohId, $consentType, (int) $granted, $on, $by, $evidence, $editor->id]);
        $e = Entities::get($db, $ohId);
        Entities::addRevision($db, $ohId, $editor->id, 'Consent updated: ' . str_replace('_', ' ', $consentType), $evidence);
        Audit::log($db, $editor->id, 'oral_history.consent_changed', 'oral_history', $e['public_id'],
            ['type' => $consentType, 'granted' => $granted, 'evidence' => $evidence]);
        self::sync($db, $ohId, $editor->id, "Consent changed: {$consentType}");
    }

    /** Embargo, transcript review and redaction notes. */
    public static function setControls(Db $db, CurrentUser $editor, int $ohId, array $form): void
    {
        $emb = substr(trim((string) ($form['embargo_until'] ?? '')), 0, 10) ?: null;
        if ($emb !== null) {
            $d = \DateTimeImmutable::createFromFormat('!Y-m-d', $emb);
            if (!$d || $d->format('Y-m-d') !== $emb) {
                throw new ConsentError('Use a date like 2030-01-31.');
            }
        }
        $reviewed = (int) (($form['transcript_reviewed'] ?? null) === '1');
        $notes = mb_substr(trim((string) ($form['redaction_notes'] ?? '')), 0, 5000) ?: null;
        $reason = mb_substr(Util::squash($form['reason'] ?? ''), 0, 1000);
        if ($reason === '') {
            throw new ConsentError('Please record a reason. It is kept in the audit log.');
        }
        $old = $db->one('SELECT embargo_until, transcript_reviewed, redaction_notes FROM oral_histories WHERE entity_id=?', [$ohId]);
        $db->exec('UPDATE oral_histories SET embargo_until=?, transcript_reviewed=?, redaction_notes=? WHERE entity_id=?', [$emb, $reviewed, $notes, $ohId]);
        Entities::addRevision($db, $ohId, $editor->id, 'Access controls updated', $reason);
        Audit::log($db, $editor->id, 'oral_history.controls_changed', 'oral_history', Entities::get($db, $ohId)['public_id'],
            ['before' => $old, 'after' => ['embargo_until' => $emb, 'transcript_reviewed' => $reviewed], 'reason' => $reason]);
        self::sync($db, $ohId, $editor->id, $reason);
    }

    public static function subjects(Db $db, int $ohId, bool $publicOnly = true): array
    {
        $q = 'SELECT e.* FROM oral_history_subjects s JOIN entities e ON e.id=s.subject_id WHERE s.oral_history_id=?';
        if ($publicOnly) {
            $q .= ' AND ' . Entities::PUBLIC_WHERE;
        }
        $out = [];
        foreach ($db->all($q . ' ORDER BY e.kind, e.id', [$ohId]) as $e) {
            $t = $db->val('SELECT ' . Entities::TITLE_COL[$e['kind']] . ' FROM ' . Entities::KIND_TABLE[$e['kind']] . ' WHERE entity_id=?', [$e['id']]);
            $out[] = ['kind' => $e['kind'], 'slug' => $e['slug'], 'public_id' => $e['public_id'], 'title' => $t];
        }
        return $out;
    }
}
