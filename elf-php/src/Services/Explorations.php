<?php
declare(strict_types=1);

namespace Elf\Services;

use Elf\Db;
use Elf\Queries;

/**
 * Curated explorations: an editor's saved selection of reviewed records about a period, a region or a theme, with a
 * description, the sources it rests on and the editor's name. It is a list of real records, not a slideshow: what
 * visitors see is always each record as it is now, and only while that record is public.
 *
 * Rules:
 * - every record added must be published and public when it is added (checked here, on the server);
 * - a record that later becomes private, unpublished or merged simply drops out of the public view;
 * - an exploration with no public record left is not listed publicly;
 * - every change is audited.
 */
final class Explorations
{
    public const ITEM_KINDS = ['place', 'event', 'person', 'family', 'organization', 'source', 'archive_item', 'oral_history', 'collection'];
    public const MAX_ITEMS = 60;

    private static function year(?string $v): ?int
    {
        $v = trim((string) $v);
        if ($v === '') {
            return null;
        }
        if (!preg_match('/^\d{4}$/', $v) || (int) $v < 1000 || (int) $v > 2100) {
            throw new ExplorationError('Give years as four digits, for example 1961.');
        }
        return (int) $v;
    }

    /** Lines of 'Name [per-abc12345]' or 'Name [per-abc12345] | why it is included'. Only public records. */
    private static function items(Db $db, ?string $text): array
    {
        $out = [];
        $seen = [];
        foreach (preg_split('/\r\n|\r|\n/', (string) $text) as $line) {
            [$ref, $note] = array_pad(explode('|', $line, 2), 2, '');
            if (trim($ref) === '') {
                continue;
            }
            $pid = null;
            if (preg_match(Records::PID_IN_BRACKETS, Util::squash($ref), $m)) {
                $pid = $m[1];
            } elseif (preg_match('/^\s*([a-z]{3}-[a-z0-9]{8})\s*$/', $ref, $m)) {
                $pid = $m[1];
            }
            $e = $pid ? Entities::getPublicByPublicId($db, $pid) : null;
            if (!$e || !in_array($e['kind'], self::ITEM_KINDS, true)) {
                throw new ExplorationError('“' . mb_substr(trim($ref), 0, 80) . '” is not a published, public record. Choose records from the suggestions.');
            }
            if (isset($seen[$e['id']])) {
                continue;
            }
            $seen[$e['id']] = true;
            $out[] = [(int) $e['id'], mb_substr(Util::squash($note), 0, 500) ?: null];
        }
        if (count($out) > self::MAX_ITEMS) {
            throw new ExplorationError('An exploration can hold at most ' . self::MAX_ITEMS . ' records.');
        }
        return $out;
    }

    private static function values(Db $db, array $form): array
    {
        $title = mb_substr(Util::squash($form['title'] ?? ''), 0, 200);
        $description = mb_substr(trim((string) ($form['description'] ?? '')), 0, 4000);
        if ($title === '' || $description === '') {
            throw new ExplorationError('Give the exploration a title and a description.');
        }
        $frm = self::year($form['period_from'] ?? null);
        $to = self::year($form['period_to'] ?? null);
        if ($frm && $to && $frm > $to) {
            throw new ExplorationError('The period must start before it ends.');
        }
        $items = self::items($db, $form['items'] ?? null);
        $published = (int) (($form['is_published'] ?? null) === '1');
        if ($published && !$items) {
            throw new ExplorationError('Add at least one record before publishing.');
        }
        return [['title' => $title, 'description' => $description, 'sources_note' => mb_substr(trim((string) ($form['sources_note'] ?? '')), 0, 4000) ?: null,
            'period_from' => $frm, 'period_to' => $to, 'region' => mb_substr(Util::squash($form['region'] ?? ''), 0, 200) ?: null,
            'is_published' => $published], $items];
    }

    private static function uniqueSlug(Db $db, string $title, ?int $ownId = null): string
    {
        $base = Names::slugify($title, 'exploration');
        $slug = $base;
        $n = 2;
        while ($db->one('SELECT 1 FROM explorations WHERE slug=? AND id IS NOT ?', [$slug, $ownId])) {
            $slug = "{$base}-{$n}";
            $n++;
        }
        return $slug;
    }

    private static function setItems(Db $db, int $xid, array $items): void
    {
        $db->exec('DELETE FROM exploration_items WHERE exploration_id=?', [$xid]);
        foreach ($items as $pos => [$eid, $note]) {
            $db->exec('INSERT INTO exploration_items(exploration_id, entity_id, position, note) VALUES (?,?,?,?)', [$xid, $eid, $pos + 1, $note]);
        }
    }

    public static function create(Db $db, CurrentUser|int $editor, array $form): int
    {
        $editorId = is_int($editor) ? $editor : $editor->id;
        [$vals, $items] = self::values($db, $form);
        $slug = self::uniqueSlug($db, $vals['title']);
        $xid = $db->insert('INSERT INTO explorations(slug, ' . implode(', ', array_keys($vals)) . ', created_by, updated_by) VALUES (?,'
            . implode(',', array_fill(0, count($vals), '?')) . ',?,?)', [$slug, ...array_values($vals), $editorId, $editorId]);
        self::setItems($db, $xid, $items);
        Audit::log($db, $editorId, 'exploration.created', 'exploration', $slug, $vals + ['items' => count($items)]);
        return $xid;
    }

    public static function update(Db $db, CurrentUser $editor, int $xid, array $form): void
    {
        $old = $db->one('SELECT * FROM explorations WHERE id=?', [$xid]);
        if (!$old) {
            throw new ExplorationError('Exploration not found.');
        }
        [$vals, $items] = self::values($db, $form);
        $db->exec('UPDATE explorations SET ' . implode(', ', array_map(fn ($k) => "{$k}=?", array_keys($vals))) . ', updated_by=?, updated_at=? WHERE id=?',
            [...array_values($vals), $editor->id, Util::nowIso(), $xid]);
        self::setItems($db, $xid, $items);
        Audit::log($db, $editor->id, 'exploration.updated', 'exploration', $old['slug'],
            ['before' => array_intersect_key($old, $vals), 'after' => $vals, 'items' => count($items)]);
    }

    public static function delete(Db $db, CurrentUser $editor, int $xid): void
    {
        $old = $db->one('SELECT slug, title FROM explorations WHERE id=?', [$xid]);
        if ($old) {
            $db->exec('DELETE FROM explorations WHERE id=?', [$xid]);
            Audit::log($db, $editor->id, 'exploration.deleted', 'exploration', $old['slug'], ['title' => $old['title']]);
        }
    }

    /** The items as the editing form shows them. */
    public static function formItems(Db $db, int $xid): string
    {
        $lines = [];
        foreach ($db->all('SELECT e.public_id, i.note FROM exploration_items i JOIN entities e ON e.id=i.entity_id WHERE i.exploration_id=? ORDER BY i.position', [$xid]) as $r) {
            $lines[] = Records::refLabel($db, $r['public_id']) . ($r['note'] ? " | {$r['note']}" : '');
        }
        return implode("\n", $lines);
    }

    /** The exploration's records that are public NOW, in the editor's order, each with its title and address. */
    public static function publicItems(Db $db, int $xid): array
    {
        $out = [];
        foreach ($db->all('SELECT e.id, e.kind, e.slug, e.public_id, e.is_fictional_test, i.note FROM exploration_items i '
            . 'JOIN entities e ON e.id=i.entity_id AND ' . Entities::PUBLIC_WHERE . ' WHERE i.exploration_id=? ORDER BY i.position', [$xid]) as $r) {
            if ($r['kind'] === 'archive_item' && !$db->one('SELECT 1 FROM archive_items a WHERE a.entity_id=? AND ' . Queries::publicItem(), [$r['id']])) {
                continue;                       // its own access level or rights do not allow public display
            }
            $t = $db->val('SELECT ' . Entities::TITLE_COL[$r['kind']] . ' FROM ' . Entities::KIND_TABLE[$r['kind']] . ' WHERE entity_id=?', [$r['id']]);
            $out[] = ['id' => $r['public_id'], 'kind' => $r['kind'], 'title' => $t, 'url' => Queries::recordUrl($r['kind'], $r['slug']),
                'note' => $r['note'], 'fictional' => (bool) $r['is_fictional_test']];
        }
        return $out;
    }

    /** Published explorations that still have at least one public record (or the one with this slug). */
    public static function published(Db $db, ?string $slug = null): array
    {
        $rows = $db->all('SELECT x.*, COALESCE(u.display_name, u.username) AS curator FROM explorations x '
            . 'LEFT JOIN users u ON u.id=x.created_by WHERE x.is_published=1' . ($slug ? ' AND x.slug=?' : '')
            . ' ORDER BY x.period_from IS NULL, x.period_from, lower(x.title)', $slug ? [$slug] : []);
        $out = [];
        foreach ($rows as $r) {
            $items = self::publicItems($db, (int) $r['id']);
            if ($items) {
                $out[] = ['x' => $r, 'items' => $items];
            }
        }
        return $out;
    }
}
