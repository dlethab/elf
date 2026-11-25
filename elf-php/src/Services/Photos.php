<?php
declare(strict_types=1);

namespace Elf\Services;

use Elf\Db;
use Elf\Vocab;

/**
 * Photographs, documents and recordings attached to contributions.
 *
 * Lifecycle:
 *   1. A contributor uploads a file to their own DRAFT (or returned) submission, with a caption, photographer, date
 *      and an honest statement of its rights. Nothing is public.
 *   2. While reviewing, an editor decides per file: include or leave out, public or restricted, and the rights status
 *      they have established. A file can only be public with rights that allow it.
 *   3. Publishing the submission turns each included file into an archive item linked to the record.
 *
 * File safety: the type is checked from the file's CONTENT, never its name; size and pixel count are limited; files
 * are stored under random keys outside the web root. Visitors only ever get re-encoded copies (display size and
 * thumbnail) with all embedded metadata removed, including GPS location. The untouched original is preserved for the
 * archive and is visible to staff only.
 */
final class Photos
{
    public const FORMATS = ['JPEG' => 'image/jpeg', 'PNG' => 'image/png', 'WEBP' => 'image/webp'];
    public const DISPLAY_SIDE = 1600;
    public const THUMB_SIDE = 480;
    public const MAX_PIXELS = 60_000_000;          // larger images are refused (decompression-bomb guard)
    public const REVIEW_STATES = ['submitted', 'under_review', 'approved'];
    public const NOT_A_PHOTO = 'This file is not a photo the archive can accept. Use a JPEG, PNG or WebP image.';
    public const UNSUPPORTED = 'This file type is not accepted. Use a photo or scan (JPEG, PNG, WebP), a PDF document, '
        . 'or an audio or video recording (MP3, M4A, OGG, WAV, MP4, WebM).';
    public const DEFAULT_ITEM_TYPE = ['image' => 'photograph', 'document' => 'scanned_document', 'audio' => 'audio_recording', 'video' => 'video_recording'];
    public const EXTENSIONS = ['application/pdf' => '.pdf', 'audio/mpeg' => '.mp3', 'audio/mp4' => '.m4a', 'audio/ogg' => '.ogg', 'audio/wav' => '.wav',
        'audio/flac' => '.flac', 'video/mp4' => '.mp4', 'video/webm' => '.webm', 'image/jpeg' => '.jpg', 'image/png' => '.png', 'image/webp' => '.webp'];
    /** Active content a PDF must not contain: it is an archive document, not a program. */
    public const PDF_ACTIVE = ['/JavaScript', '/JS ', '/JS(', '/JS<', '/Launch', '/EmbeddedFile', '/RichMedia', '/XFA'];

    public const TOO_LARGE_FOR_SERVER = 'This image is too large for the server to process. Please upload a smaller copy '
        . '(for example at most 6000 × 4000 pixels).';

    // ───────────── image handling ─────────────
    /**
     * GD keeps a decoded picture in memory (about 4 bytes a pixel, twice over while it is turned upright). Running out
     * of memory would stop PHP without a message, so the limit is raised when the server allows it, and otherwise the
     * picture is refused with an explanation.
     */
    public static function enoughMemory(int $w, int $h): bool
    {
        $need = (int) ($w * $h * 4 * 2.2) + 48 * 1024 * 1024 + memory_get_usage();
        $limit = self::bytes((string) ini_get('memory_limit'));
        if ($limit < 0 || $limit >= $need) {
            return true;
        }
        @ini_set('memory_limit', (string) $need);
        $limit = self::bytes((string) ini_get('memory_limit'));
        return $limit < 0 || $limit >= $need;
    }

    private static function bytes(string $v): int
    {
        $v = trim($v);
        if ($v === '' || $v === '-1') {
            return -1;
        }
        $n = (int) $v;
        return match (strtolower(substr($v, -1))) {
            'g' => $n * 1024 ** 3, 'm' => $n * 1024 ** 2, 'k' => $n * 1024, default => $n,
        };
    }

    /** @return array{0:\GdImage,1:string} the decoded image and its format (JPEG, PNG, WEBP) */
    public static function identify(string $data): array
    {
        $info = @getimagesizefromstring($data);
        $fmt = match ($info[2] ?? null) {
            IMAGETYPE_JPEG => 'JPEG', IMAGETYPE_PNG => 'PNG', IMAGETYPE_WEBP => 'WEBP', default => null,
        };
        if (!$info || !$fmt) {
            throw new PhotoError(['photo' => self::NOT_A_PHOTO]);
        }
        if ($info[0] < 1 || $info[1] < 1 || $info[0] * $info[1] > self::MAX_PIXELS) {
            throw new PhotoError(['photo' => self::NOT_A_PHOTO]);
        }
        if (!self::enoughMemory((int) $info[0], (int) $info[1])) {
            throw new PhotoError(['photo' => self::TOO_LARGE_FOR_SERVER]);
        }
        $im = @imagecreatefromstring($data);
        if (!$im) {
            throw new PhotoError(['photo' => self::NOT_A_PHOTO]);
        }
        return [$im, $fmt];
    }

    /** EXIF orientation of a JPEG (1 = upright), read without trusting anything else in the metadata. */
    private static function orientation(string $data, string $fmt): int
    {
        if ($fmt !== 'JPEG' || !function_exists('exif_read_data')) {
            return 1;
        }
        $exif = @exif_read_data('data://image/jpeg;base64,' . base64_encode($data), 'IFD0');
        $o = (int) ($exif['Orientation'] ?? 1);
        return ($o >= 1 && $o <= 8) ? $o : 1;
    }

    /**
     * A re-encoded JPEG copy, at most $side pixels on its longer edge (never enlarged). Nothing embedded in the
     * original (EXIF, GPS, comments) is carried over; the picture is turned upright first.
     * @return array{0:string,1:array{0:int,1:int}}
     */
    public static function derive(\GdImage $src, int $side, int $orientation = 1): array
    {
        $im = $src;
        if ($orientation !== 1) {
            $im = imagecrop($src, ['x' => 0, 'y' => 0, 'width' => imagesx($src), 'height' => imagesy($src)]);
            if (in_array($orientation, [2, 4, 5, 7], true)) {
                imageflip($im, IMG_FLIP_HORIZONTAL);
            }
            $rot = match ($orientation) { 3, 4 => 180, 5, 6 => 270, 7, 8 => 90, default => 0 };
            if ($rot) {
                $im = imagerotate($im, $rot, 0);
            }
        }
        $w = imagesx($im);
        $h = imagesy($im);
        $scale = min(1.0, $side / max($w, $h));
        $nw = max(1, (int) round($w * $scale));
        $nh = max(1, (int) round($h * $scale));
        $out = imagecreatetruecolor($nw, $nh);
        imagefill($out, 0, 0, imagecolorallocate($out, 255, 255, 255));       // transparent areas become white
        imagecopyresampled($out, $im, 0, 0, 0, 0, $nw, $nh, $w, $h);
        imageinterlace($out, true);
        ob_start();
        imagejpeg($out, null, 85);
        $bytes = (string) ob_get_clean();
        return [$bytes, [$nw, $nh]];
    }

    // ───────────── metadata ─────────────
    public static function validateMeta(array $form): array
    {
        $errors = [];
        $text = function (string $name, int $limit) use ($form, &$errors) {
            $v = Util::squash($form[$name] ?? '');
            if (mb_strlen($v, 'UTF-8') > $limit) {
                $errors[$name] = 'This is too long.';
            }
            return $v !== '' ? $v : null;
        };
        $clean = ['caption' => $text('caption', 500), 'creator_text' => $text('creator_text', 200),
            'place_note' => $text('place_note', 1000), 'people_note' => $text('people_note', 1000),
            'rights_holder' => $text('rights_holder', 300)];
        if (!$clean['caption']) {
            $errors['caption'] = 'Describe what the photo shows.';
        }
        try {
            $clean['taken'] = Dates::parse($form['taken'] ?? '');
        } catch (DateError) {
            $errors['taken'] = 'Use a form like 1952, 1952-03, 1952-03-14, c. 1952, 1950s, or 1950 to 1955.';
            $clean['taken'] = new FuzzyDate();
        }
        $rights = trim((string) ($form['rights_status'] ?? ''));
        if (!in_array($rights, Vocab::CONTRIBUTOR_RIGHTS, true)) {
            $errors['rights_status'] = 'Choose one of the listed options.';
        }
        $clean['rights_status'] = $rights;
        if (($form['rights_declared'] ?? null) !== '1') {
            $errors['rights_declared'] = 'Please confirm this statement to upload the photo.';
        }
        return [$clean, $errors];
    }

    // ───────────── contributor actions ─────────────
    private static function ownEditable(Db $db, CurrentUser $user, int $sid): array
    {
        $s = $db->one('SELECT * FROM submissions WHERE id=?', [$sid]);
        if (!$s || $s['submitter_id'] !== $user->id) {
            throw new PermissionDenied('Not your submission.');
        }
        if (!in_array($s['status'], Workflow::EDITABLE, true)) {
            throw new WorkflowError('Photos can only be added or removed while the submission is a draft or has been returned to you.');
        }
        if (!in_array($s['kind'], Workflow::PHOTO_KINDS, true)) {
            throw new WorkflowError('Photos cannot be attached to a relationship proposal.');
        }
        return $s;
    }

    /** [media_kind, mime] from a file's first bytes, or [null, null]. Never from the file name. */
    public static function sniff(string $head): array
    {
        if (str_starts_with($head, "\xff\xd8\xff") || str_starts_with($head, "\x89PNG\r\n\x1a\n") || (substr($head, 0, 4) === 'RIFF' && substr($head, 8, 4) === 'WEBP')) {
            return ['image', null];
        }
        if (str_starts_with($head, '%PDF-')) {
            return ['document', 'application/pdf'];
        }
        if (str_starts_with($head, 'ID3') || (strlen($head) > 1 && ord($head[0]) === 0xFF && (ord($head[1]) & 0xE0) === 0xE0)) {
            return ['audio', 'audio/mpeg'];
        }
        if (str_starts_with($head, 'OggS')) {
            return ['audio', 'audio/ogg'];
        }
        if (str_starts_with($head, 'fLaC')) {
            return ['audio', 'audio/flac'];
        }
        if (substr($head, 0, 4) === 'RIFF' && substr($head, 8, 4) === 'WAVE') {
            return ['audio', 'audio/wav'];
        }
        if (substr($head, 4, 4) === 'ftyp') {
            return in_array(substr($head, 8, 3), ['M4A', 'M4B'], true) ? ['audio', 'audio/mp4'] : ['video', 'video/mp4'];
        }
        if (str_starts_with($head, "\x1a\x45\xdf\xa3")) {
            return ['video', 'video/webm'];
        }
        return [null, null];
    }

    private static function limit(?string $kind, array $config): int
    {
        return match ($kind) {
            'image' => (int) $config['MAX_PHOTO_BYTES'],
            'document' => (int) ($config['MAX_DOCUMENT_BYTES'] ?? 30 * 1024 * 1024),
            default => (int) ($config['MAX_AV_BYTES'] ?? 250 * 1024 * 1024),
        };
    }

    /** SHA-256 of a file, and for PDFs whether it contains active content. Reads in chunks. */
    public static function hashAndScan(string $path, bool $pdf): array
    {
        $h = hash_init('sha256');
        $tail = '';
        $active = false;
        $f = fopen($path, 'rb');
        while (!feof($f)) {
            $chunk = fread($f, 1024 * 1024);
            if ($chunk === '' || $chunk === false) {
                break;
            }
            hash_update($h, $chunk);
            if ($pdf && !$active) {
                $window = $tail . $chunk;
                foreach (self::PDF_ACTIVE as $m) {
                    if (str_contains($window, $m)) {
                        $active = true;
                        break;
                    }
                }
                $tail = substr($chunk, -32);
            }
        }
        fclose($f);
        return [hash_final($h), $active];
    }

    private static function canRun(string $fn): bool
    {
        if (!function_exists($fn)) {
            return false;
        }
        $disabled = array_map('trim', explode(',', (string) ini_get('disable_functions')));
        return !in_array($fn, $disabled, true);
    }

    /**
     * With ffmpeg on the server, make a playback copy without embedded metadata (no re-encoding).
     * Returns [key, size, sha256] or null. Without ffmpeg (most shared hosting) the original is used for playback.
     */
    private static function stripAvMetadata(Storage $store, string $key, ?string $mime): ?array
    {
        if (!self::canRun('proc_open')) {
            return null;
        }
        $ffmpeg = null;
        foreach (explode(PATH_SEPARATOR, (string) getenv('PATH')) as $dir) {
            foreach (['ffmpeg', 'ffmpeg.exe'] as $exe) {
                if (is_file($dir . DIRECTORY_SEPARATOR . $exe)) {
                    $ffmpeg = $dir . DIRECTORY_SEPARATOR . $exe;
                    break 2;
                }
            }
        }
        if (!$ffmpeg) {
            return null;
        }
        $out = tempnam(sys_get_temp_dir(), 'elf') . (self::EXTENSIONS[$mime] ?? '');
        try {
            $p = proc_open([$ffmpeg, '-v', 'error', '-y', '-i', $store->path($key), '-map', '0', '-map_metadata', '-1',
                '-map_chapters', '-1', '-c', 'copy', $out], [1 => ['pipe', 'w'], 2 => ['pipe', 'w']], $pipes);
            if (!is_resource($p)) {
                return null;
            }
            stream_get_contents($pipes[1]);
            stream_get_contents($pipes[2]);
            if (proc_close($p) !== 0 || !is_file($out)) {
                return null;
            }
            $new = Storage::newKey();
            $store->putFile($new, $out);
            [$digest] = self::hashAndScan($out, false);
            return [$new, filesize($out), $digest];
        } catch (\Throwable) {
            return null;
        } finally {
            @unlink($out);
        }
    }

    /**
     * Validate and store one file (photo, document, audio or video) on the user's own editable submission.
     * $upload: ['path' => temporary file, 'name' => original file name] or null when nothing was chosen.
     * Returns the attachment id.
     */
    public static function add(Db $db, Storage $store, CurrentUser $user, int $sid, ?array $upload, array $form, array $config): int
    {
        if (($config['REQUIRE_EMAIL_VERIFICATION'] ?? true) && !$user->email_verified) {
            throw new PermissionDenied('Please verify your email address before uploading photos.');
        }
        self::ownEditable($db, $user, $sid);
        $path = $upload['path'] ?? null;
        $filename = $upload['name'] ?? null;
        $size = ($path && is_file($path)) ? (int) filesize($path) : 0;
        $head = $size ? (string) file_get_contents($path, false, null, 0, 64) : '';
        [$clean, $errors] = self::validateMeta($form);
        [$kind, $mime] = $size ? self::sniff($head) : [null, null];
        $itemType = ($form['item_type'] ?? '') ?: (self::DEFAULT_ITEM_TYPE[$kind] ?? 'other');
        if (!in_array($itemType, Vocab::ITEM_TYPES, true)) {
            $errors['item_type'] = 'Choose one of the listed options.';
        }
        $transcript = mb_substr(trim(str_replace("\r\n", "\n", (string) ($form['transcript'] ?? ''))), 0, 100000) ?: null;
        if (!$size) {
            $errors['photo'] = 'Choose a photo to upload.';
        } elseif ($kind === null) {
            $errors['photo'] = self::UNSUPPORTED;
        } elseif ($size > self::limit($kind, $config)) {
            $errors['photo'] = 'This photo is too large. Reduce its size and try again.';
        }
        if ($errors) {
            throw new PhotoError($errors);
        }
        if (self::count($db, $sid) >= (int) $config['MAX_PHOTOS_PER_SUBMISSION']) {
            throw new PhotoError(['photo' => 'This submission already has the maximum number of photos.']);
        }
        if (!RateLimit::allow($db, "upload:{$user->id}", 60, 3600)) {
            throw new PhotoError(['photo' => 'You have uploaded many photos recently. Please wait a while before adding more.']);
        }
        $data = null;
        if ($kind === 'image') {
            $data = (string) file_get_contents($path);
            [$im, $fmt] = self::identify($data);
            $digest = hash('sha256', $data);
        } else {
            [$digest, $active] = self::hashAndScan($path, $kind === 'document');
            if ($active) {
                throw new PhotoError(['photo' => 'This PDF contains active content (scripts or embedded files), which the archive does not accept. '
                    . 'Print it to a new PDF or scan it, and upload that instead.']);
            }
        }
        if ($db->one("SELECT 1 FROM media_files WHERE submission_id=? AND file_role='original' AND sha256=?", [$sid, $digest])) {
            throw new PhotoError(['photo' => 'This photo is already attached to this submission.']);
        }
        $written = [];
        $files = [];
        try {
            if ($kind === 'image') {
                $orient = self::orientation($data, $fmt);
                [$display, $dsize] = self::derive($im, self::DISPLAY_SIDE, $orient);
                [$thumb, $tsize] = self::derive($im, self::THUMB_SIDE, $orient);
                foreach ([[$data, self::FORMATS[$fmt], [imagesx($im), imagesy($im)], 'original'], [$display, 'image/jpeg', $dsize, 'access_derivative'],
                             [$thumb, 'image/jpeg', $tsize, 'thumbnail']] as [$blob, $m, $wh, $role]) {
                    $key = Storage::newKey();
                    $store->put($key, $blob);
                    $written[] = $key;
                    $files[] = [$key, $m, strlen($blob), $wh[0], $wh[1], hash('sha256', $blob), $role];
                }
            } else {
                $key = Storage::newKey();
                $store->putFile($key, $path);
                $written[] = $key;
                $files[] = [$key, $mime, $size, null, null, $digest, 'original'];
                if (in_array($kind, ['audio', 'video'], true)) {
                    $stripped = self::stripAvMetadata($store, $key, $mime);
                    if ($stripped) {
                        $written[] = $stripped[0];
                        $files[] = [$stripped[0], $mime, $stripped[1], null, null, $stripped[2], 'access_derivative'];
                    }
                }
            }
            return $db->tx(function () use ($db, $sid, $files, $filename, $user, $clean, $kind, $itemType, $transcript, $digest) {
                $origId = null;
                foreach ($files as [$key, $m, $sz, $w, $h, $sha, $role]) {
                    $id = $db->insert('INSERT INTO media_files(submission_id, storage_key, original_filename, mime_type, size_bytes, width, height, '
                        . "sha256, file_role, derived_from_id, access_level, processing_status, uploaded_by) VALUES (?,?,?,?,?,?,?,?,?,?, 'private', 'done', ?)",
                        [$sid, $key, mb_substr((string) $filename, 0, 200) ?: null, $m, $sz, $w, $h, $sha, $role, $origId, $user->id]);
                    $origId ??= $id;
                }
                $taken = $clean['taken'];
                $pid = $db->insert('INSERT INTO submission_photos(submission_id, original_media_id, caption, creator_text, taken_start, taken_end, '
                    . 'taken_precision, taken_note, place_note, people_note, rights_holder, rights_status, rights_declared, media_kind, item_type, transcript) '
                    . 'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?)',
                    [$sid, $origId, $clean['caption'], $clean['creator_text'], $taken->start, $taken->end, $taken->precision, $taken->note,
                        $clean['place_note'], $clean['people_note'], $clean['rights_holder'], $clean['rights_status'], $kind, $itemType, $transcript]);
                $db->exec('UPDATE submissions SET updated_at=? WHERE id=?', [Util::nowIso(), $sid]);
                Audit::log($db, $user->id, 'photo.uploaded', 'submission', $sid, ['photo' => $pid, 'sha256' => $digest, 'kind' => $kind]);
                return $pid;
            });
        } catch (\Throwable $e) {
            foreach ($written as $k) {               // never leave stored files without a database row
                $store->delete($k);
            }
            throw $e;
        }
    }

    /** Contributors may remove their own photo before review. Not yet an archive record, so it is deleted. */
    public static function remove(Db $db, Storage $store, CurrentUser $user, int $sid, int $photoId): void
    {
        $keys = $db->tx(function () use ($db, $user, $sid, $photoId) {
            self::ownEditable($db, $user, $sid);
            $p = $db->one('SELECT * FROM submission_photos WHERE id=? AND submission_id=?', [$photoId, $sid]);
            if (!$p) {
                throw new WorkflowError('Photo not found.');
            }
            $keys = $db->col('SELECT storage_key FROM media_files WHERE id=? OR derived_from_id=?', [$p['original_media_id'], $p['original_media_id']]);
            $db->exec('DELETE FROM submission_photos WHERE id=?', [$photoId]);
            $db->exec('DELETE FROM media_files WHERE derived_from_id=?', [$p['original_media_id']]);
            $db->exec('DELETE FROM media_files WHERE id=?', [$p['original_media_id']]);
            Audit::log($db, $user->id, 'photo.removed', 'submission', $sid, ['photo' => $photoId]);
            return $keys;
        });
        foreach ($keys as $k) {
            $store->delete($k);
        }
    }

    // ───────────── reading ─────────────
    public static function count(Db $db, int $sid): int
    {
        return (int) $db->val('SELECT COUNT(*) FROM submission_photos WHERE submission_id=?', [$sid]);
    }

    public static function pendingCount(Db $db, int $sid): int
    {
        return (int) $db->val("SELECT COUNT(*) FROM submission_photos WHERE submission_id=? AND editor_decision='pending'", [$sid]);
    }

    public static function listForSubmission(Db $db, int $sid): array
    {
        return $db->all('SELECT p.*, o.storage_key AS original_key, o.original_filename, o.size_bytes, o.width, o.height, o.mime_type, o.sha256, '
            . "(SELECT storage_key FROM media_files WHERE derived_from_id=o.id AND file_role='thumbnail') AS thumb_key, "
            . "(SELECT storage_key FROM media_files WHERE derived_from_id=o.id AND file_role='access_derivative') AS display_key, "
            . 'e.public_id AS item_public_id, e.visibility AS item_visibility '
            . 'FROM submission_photos p JOIN media_files o ON o.id=p.original_media_id '
            . 'LEFT JOIN entities e ON e.id=p.result_item_id WHERE p.submission_id=? ORDER BY p.id', [$sid]);
    }

    /**
     * Vetted researchers may see published material that is RESTRICTED (never private or embargoed): archive items,
     * and oral histories whose interviewee consented to research access.
     */
    public static function researchAccess(Db $db, ?CurrentUser $user, int $entityId, bool $requireStaffMfa = false): bool
    {
        if (!($user && $user->can('restricted.view'))) {
            return false;
        }
        if ($requireStaffMfa && !$user->mfa_enabled) {
            return false;                       // the staff two-step policy covers research access too
        }
        $e = Entities::get($db, $entityId);
        if (!$e || $e['publication_status'] !== 'published' || $e['visibility'] !== 'restricted' || $e['merged_into'] || $e['deleted_at']) {
            return false;
        }
        if ($e['kind'] === 'archive_item') {
            $a = $db->one('SELECT access_level, rights_status FROM archive_items WHERE entity_id=?', [$entityId]);
            if (in_array($a['access_level'], ['private', 'embargoed'], true) || $a['rights_status'] === 'private_embargoed') {
                return false;
            }
            $oh = $db->one('SELECT entity_id FROM oral_histories WHERE media_item_id=?', [$entityId]);
            return $oh === null || self::consentGranted($db, (int) $oh['entity_id'], 'research_access');
        }
        if ($e['kind'] === 'oral_history') {
            return self::consentGranted($db, $entityId, 'research_access');
        }
        return false;
    }

    public static function consentGranted(Db $db, int $oralHistoryId, string $consentType): bool
    {
        $r = $db->one('SELECT granted FROM consent_records WHERE oral_history_id=? AND consent_type=? AND revoked_at IS NULL', [$oralHistoryId, $consentType]);
        return (bool) ($r && $r['granted']);
    }

    /**
     * The single access rule for every stored file. Called on EVERY request for a file, so a copied or guessed URL is
     * worth nothing without the right to see the file.
     */
    public static function canViewMedia(Db $db, ?CurrentUser $user, array $m, bool $requireStaffMfa = false): bool
    {
        if ($user && $user->can('record.view_any')) {
            return true;
        }
        if ($m['owner_id'] !== null) {
            if ($m['file_role'] === 'original' && (str_starts_with((string) $m['mime_type'], 'image/')
                    || $db->one("SELECT 1 FROM media_files WHERE derived_from_id=? AND file_role='access_derivative'", [$m['id']]))) {
                return false;      // when a cleaned copy exists, the original (with its embedded metadata) is staff-only
            }
            $ph = implode(',', array_fill(0, count(Vocab::PUBLIC_RIGHTS), '?'));
            $r = $db->one('SELECT 1 FROM entities e JOIN archive_items a ON a.entity_id=e.id WHERE e.id=? AND ' . Entities::PUBLIC_WHERE
                . " AND a.access_level='public' AND a.rights_status IN ({$ph})", [$m['owner_id'], ...Vocab::PUBLIC_RIGHTS]);
            if ($r !== null) {
                return true;
            }
            return self::researchAccess($db, $user, (int) $m['owner_id'], $requireStaffMfa);
        }
        $s = $db->one('SELECT submitter_id FROM submissions WHERE id=?', [$m['submission_id']]);
        return (bool) ($user && $s && $s['submitter_id'] === $user->id);
    }

    // ───────────── editor actions ─────────────
    public static function decide(Db $db, CurrentUser $user, int $sid, int $photoId, array $form, array $config): void
    {
        if (!$user->can('submission.review')) {
            throw new PermissionDenied('You do not have permission for this action.');
        }
        $db->tx(function () use ($db, $user, $sid, $photoId, $form, $config) {
            $s = $db->one('SELECT * FROM submissions WHERE id=?', [$sid]);
            $p = $db->one('SELECT * FROM submission_photos WHERE id=? AND submission_id=?', [$photoId, $sid]);
            if (!$s || !$p) {
                throw new WorkflowError('Photo not found.');
            }
            if (!in_array($s['status'], self::REVIEW_STATES, true)) {
                throw new WorkflowError('Photo decisions can only be made while the submission is being reviewed.');
            }
            if ($s['submitter_id'] === $user->id && !($config['ALLOW_SELF_REVIEW'] ?? false)) {
                throw new PermissionDenied('You cannot review your own submission. Another editor must do this.');
            }
            $decision = $form['decision'] ?? null;
            $access = ($form['access'] ?? '') ?: 'restricted';
            $rights = ($form['rights_status'] ?? '') ?: $p['rights_status'];
            if (!in_array($decision, ['accept', 'decline'], true) || !in_array($access, ['public', 'restricted'], true)
                || !in_array($rights, Vocab::RIGHTS_STATUSES, true)) {
                throw new WorkflowError('Choose one of the listed options.');
            }
            if ($decision === 'decline') {
                $access = 'restricted';
            }
            if ($access === 'public' && !in_array($rights, Vocab::PUBLIC_RIGHTS, true)) {
                throw new WorkflowError('A photo can be public only when its rights allow it: public domain, permission granted, or licensed for use.');
            }
            $caption = mb_substr(Util::squash($form['published_caption'] ?? ''), 0, 500) ?: $p['caption'];
            $note = mb_substr(trim((string) ($form['editor_note'] ?? '')), 0, 2000) ?: null;
            $db->exec('UPDATE submission_photos SET editor_decision=?, editor_access=?, editor_rights_status=?, published_caption=?, '
                . 'editor_note=?, decided_by=? WHERE id=?', [$decision, $access, $rights, $caption, $note, $user->id, $photoId]);
            Audit::log($db, $user->id, 'photo.decided', 'submission', $sid, ['photo' => $photoId, 'decision' => $decision, 'access' => $access, 'rights' => $rights]);
        });
    }

    private static function title(string $caption): string
    {
        if (mb_strlen($caption, 'UTF-8') <= 120) {
            return $caption;
        }
        $cut = mb_substr($caption, 0, 120, 'UTF-8');
        $pos = mb_strrpos($cut, ' ', 0, 'UTF-8');
        return ($pos !== false ? mb_substr($cut, 0, $pos, 'UTF-8') : $cut) . '…';
    }

    /** Inside the publication transaction: turn included photos into archive items linked to the record. */
    public static function publishForSubmission(Db $db, array $s, int $recordId, ?int $actorId): int
    {
        $photos = $db->all('SELECT * FROM submission_photos WHERE submission_id=? ORDER BY id', [$s['id']]);
        if (!$photos) {
            return 0;
        }
        foreach ($photos as $p) {
            if ($p['editor_decision'] === 'pending') {
                throw new WorkflowError('Decide on every photo (include it or leave it out) before publishing.');
            }
        }
        $record = $db->one('SELECT e.* FROM entities e WHERE e.id=? AND ' . Entities::PUBLIC_WHERE, [$recordId]);
        $raw = Entities::get($db, $recordId);
        $added = 0;
        foreach ($photos as $p) {
            if ($p['editor_decision'] !== 'accept') {
                continue;
            }
            $rights = $p['editor_rights_status'] ?: $p['rights_status'];
            // A photo of a restricted record (e.g. a living person without consent) is never public.
            $public = $p['editor_access'] === 'public' && in_array($rights, Vocab::PUBLIC_RIGHTS, true) && $record !== null;
            $vis = $public ? 'public' : 'restricted';
            $caption = $p['published_caption'] ?: $p['caption'];
            $title = self::title($caption);
            [$eid, $pid] = Entities::create($db, 'archive_item', $title, $actorId, 'published', $vis, (bool) $raw['is_fictional_test']);
            $db->exec('INSERT INTO archive_items(entity_id, title, item_type, description, created_start, created_end, created_precision, '
                . 'created_note, creator, uploaded_by, provenance, rights_holder, rights_status, access_level, media_kind, transcript) '
                . 'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                [$eid, $title, $p['item_type'], $caption !== $title ? $caption : null, $p['taken_start'], $p['taken_end'], $p['taken_precision'],
                    $p['taken_note'], $p['creator_text'], $s['submitter_id'], 'Contributed to the archive and reviewed by an editor.',
                    $p['rights_holder'], $rights, $vis, $p['media_kind'], $p['transcript']]);
            Entities::addName($db, $eid, $title, 'preferred');
            $db->exec('INSERT INTO archive_item_subjects(item_id, subject_id) VALUES (?,?)', [$eid, $recordId]);
            $db->exec('UPDATE media_files SET owner_id=?, access_level=? WHERE id=? OR derived_from_id=?', [$eid, $vis, $p['original_media_id'], $p['original_media_id']]);
            $db->exec('UPDATE submission_photos SET result_item_id=? WHERE id=?', [$eid, $p['id']]);
            Entities::addRevision($db, $eid, $actorId, 'Created from an approved contribution', null, (int) $s['id']);
            Audit::log($db, $actorId, 'archive_item.published', 'archive_item', $pid, ['submission' => (int) $s['id'], 'visibility' => $vis]);
            Search::reindex($db, $eid);
            $added++;
        }
        if ($added) {
            Entities::addRevision($db, $recordId, $actorId, "{$added} photograph" . ($added !== 1 ? 's' : '') . ' added', null, (int) $s['id']);
        }
        return $added;
    }

    /** Keep an archive item's access level and its files in step with the item's publication state. */
    public static function syncItemAccess(Db $db, int $itemId): void
    {
        $e = Entities::get($db, $itemId);
        $public = $e['publication_status'] === 'published' && $e['visibility'] === 'public' && !$e['deleted_at'];
        $level = $public ? 'public' : 'restricted';
        $db->exec('UPDATE archive_items SET access_level=? WHERE entity_id=?', [$level, $itemId]);
        $db->exec('UPDATE media_files SET access_level=? WHERE owner_id=?', [$level, $itemId]);
    }
}
