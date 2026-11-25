<?php
declare(strict_types=1);

namespace Elf\Services;

use Elf\Db;
use Elf\Queries;

/**
 * Curated collections of archive items. Editors create and arrange them; a collection page shows only the items that
 * are themselves public, so a public collection never exposes a restricted photo or document.
 */
final class Collections
{
    private static function values(array $form): array
    {
        $title = mb_substr(Util::squash($form['title'] ?? ''), 0, 300);
        if ($title === '') {
            throw new CollectionError('Give the collection a title.');
        }
        $vis = ($form['visibility'] ?? '') ?: 'public';
        if (!in_array($vis, ['public', 'restricted'], true)) {
            throw new CollectionError('Choose one of the listed options.');
        }
        return [['title' => $title, 'description' => mb_substr(trim((string) ($form['description'] ?? '')), 0, 20000) ?: null,
            'rights_note' => mb_substr(trim((string) ($form['rights_note'] ?? '')), 0, 2000) ?: null,
            'is_featured' => (int) (($form['is_featured'] ?? null) === '1')], $vis];
    }

    public static function create(Db $db, CurrentUser|int $editor, array $form): string
    {
        $editorId = is_int($editor) ? $editor : $editor->id;
        [$vals, $vis] = self::values($form);
        [$eid, $pid] = Entities::create($db, 'collection', $vals['title'], $editorId, 'published', $vis);
        $db->exec('INSERT INTO collections(entity_id, title, description, rights_note, is_featured, created_by) VALUES (?,?,?,?,?,?)',
            [$eid, $vals['title'], $vals['description'], $vals['rights_note'], $vals['is_featured'], $editorId]);
        Entities::addName($db, $eid, $vals['title'], 'preferred');
        Entities::addRevision($db, $eid, $editorId, 'Collection created');
        Audit::log($db, $editorId, 'collection.created', 'collection', $pid, $vals);
        Search::reindex($db, $eid);
        return $pid;
    }

    public static function update(Db $db, CurrentUser $editor, array $coll, array $form): void
    {
        [$vals, $vis] = self::values($form);
        $reason = mb_substr(Util::squash($form['reason'] ?? ''), 0, 1000);
        if ($reason === '') {
            throw new CollectionError('Please record a reason. It is kept in the audit log.');
        }
        $old = Entities::subtypeRow($db, (int) $coll['id']);
        $db->exec('UPDATE collections SET title=?, description=?, rights_note=?, is_featured=? WHERE entity_id=?',
            [$vals['title'], $vals['description'], $vals['rights_note'], $vals['is_featured'], $coll['id']]);
        if ($vals['title'] !== $old['title']) {
            $db->exec("UPDATE OR IGNORE entity_names SET name_type='alternate_spelling' WHERE entity_id=? AND name_type='preferred'", [$coll['id']]);
            $db->exec("DELETE FROM entity_names WHERE entity_id=? AND name_type='preferred'", [$coll['id']]);
            Entities::addName($db, (int) $coll['id'], $vals['title'], 'preferred');
        }
        if ($vis !== $coll['visibility']) {
            Entities::setState($db, (int) $coll['id'], null, $vis, $editor->id, $reason);
        }
        Entities::addRevision($db, (int) $coll['id'], $editor->id, 'Collection details updated', $reason);
        $db->exec('UPDATE entities SET updated_at=? WHERE id=?', [Util::nowIso(), $coll['id']]);
        Audit::log($db, $editor->id, 'collection.updated', 'collection', $coll['public_id'],
            ['before' => array_intersect_key($old, $vals), 'after' => $vals, 'reason' => $reason]);
        Search::reindex($db, (int) $coll['id']);
    }

    public static function addItem(Db $db, CurrentUser|int $editor, array $coll, array $form): void
    {
        $editorId = is_int($editor) ? $editor : $editor->id;
        $v = Util::squash($form['item'] ?? '');
        $pid = preg_match(Records::PID_IN_BRACKETS, $v, $m) ? $m[1] : $v;
        $item = Entities::getByPublicId($db, $pid);
        if (!$item || $item['kind'] !== 'archive_item' || $item['merged_into'] || $item['deleted_at']) {
            throw new CollectionError('That archive item was not found. Use its permanent ID, for example itm-abc12345.');
        }
        if ($db->one('SELECT 1 FROM collection_items WHERE collection_id=? AND item_id=?', [$coll['id'], $item['id']])) {
            throw new CollectionError('This item is already in the collection.');
        }
        $pos = (int) $db->val('SELECT COALESCE(MAX(position), 0) + 1 FROM collection_items WHERE collection_id=?', [$coll['id']]);
        $db->exec('INSERT INTO collection_items(collection_id, item_id, position) VALUES (?,?,?)', [$coll['id'], $item['id'], $pos]);
        Entities::addRevision($db, (int) $coll['id'], $editorId, 'Item added to the collection');
        Audit::log($db, $editorId, 'collection.item_added', 'collection', $coll['public_id'], ['item' => $item['public_id']]);
    }

    public static function removeItem(Db $db, CurrentUser $editor, array $coll, int $itemId): void
    {
        $db->exec('DELETE FROM collection_items WHERE collection_id=? AND item_id=?', [$coll['id'], $itemId]);
        Entities::addRevision($db, (int) $coll['id'], $editor->id, 'Item removed from the collection');
        Audit::log($db, $editor->id, 'collection.item_removed', 'collection', $coll['public_id'], ['item_id' => $itemId]);
    }

    public static function moveItem(Db $db, CurrentUser $editor, array $coll, int $itemId, string $direction): void
    {
        $order = array_map('intval', $db->col('SELECT item_id FROM collection_items WHERE collection_id=? ORDER BY position, item_id', [$coll['id']]));
        $i = array_search($itemId, $order, true);
        if ($i === false) {
            return;
        }
        $j = $direction === 'up' ? $i - 1 : $i + 1;
        if ($j >= 0 && $j < count($order)) {
            [$order[$i], $order[$j]] = [$order[$j], $order[$i]];
        }
        foreach ($order as $p => $iid) {
            $db->exec('UPDATE collection_items SET position=? WHERE collection_id=? AND item_id=?', [$p + 1, $coll['id'], $iid]);
        }
    }

    public static function items(Db $db, int $collId, bool $publicOnly = true): array
    {
        $where = $publicOnly ? ' AND ' . Entities::PUBLIC_WHERE . ' AND ' . Queries::publicItem() : '';
        return $db->all('SELECT e.id, e.public_id, e.slug, e.visibility, e.is_fictional_test, a.title, a.media_kind, a.item_type, a.access_level, '
            . 'a.created_start, a.created_end, a.created_precision, ' . Queries::THUMB . ' AS thumb_key FROM collection_items ci '
            . "JOIN entities e ON e.id=ci.item_id JOIN archive_items a ON a.entity_id=e.id WHERE ci.collection_id=?{$where} "
            . 'ORDER BY ci.position, e.id', [$collId]);
    }

    public static function publicList(Db $db, bool $featuredOnly = false, int $limit = 200): array
    {
        $rows = $db->all('SELECT e.id, e.slug, e.is_fictional_test, c.title, c.description, c.is_featured FROM entities e '
            . "JOIN collections c ON c.entity_id=e.id WHERE e.kind='collection' AND " . Entities::PUBLIC_WHERE
            . ($featuredOnly ? ' AND c.is_featured=1' : '') . ' ORDER BY c.is_featured DESC, lower(c.title) LIMIT ?', [$limit]);
        $out = [];
        foreach ($rows as $r) {
            $its = self::items($db, (int) $r['id']);
            if ($its) {                      // a collection with nothing public in it is not listed publicly
                $cover = null;
                foreach ($its as $i) {
                    if ($i['thumb_key']) {
                        $cover = $i;
                        break;
                    }
                }
                $out[] = ['row' => $r, 'count' => count($its), 'cover' => $cover ?? $its[0]];
            }
        }
        return $out;
    }
}
