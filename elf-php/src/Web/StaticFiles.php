<?php
declare(strict_types=1);

namespace Elf\Web;

use Elf\App;
use Elf\Config;
use Elf\Http\HttpException;
use Elf\Http\Request;
use Elf\Http\Response;

/**
 * Files from public/static (when PHP itself serves them, e.g. the built-in server; Apache and nginx serve them
 * directly) and the shared file sender: conditional requests (ETag, Last-Modified) and byte ranges for audio and video.
 */
final class StaticFiles
{
    public const TYPES = ['css' => 'text/css; charset=utf-8', 'js' => 'text/javascript; charset=utf-8', 'json' => 'application/json',
        'png' => 'image/png', 'jpg' => 'image/jpeg', 'jpeg' => 'image/jpeg', 'webp' => 'image/webp', 'svg' => 'image/svg+xml',
        'txt' => 'text/plain; charset=utf-8', 'ico' => 'image/vnd.microsoft.icon', 'woff2' => 'font/woff2', 'map' => 'application/json'];

    public static function serve(App $app, Request $req): Response
    {
        if (!in_array($req->method, ['GET', 'HEAD'], true)) {
            throw new HttpException(405);
        }
        $rel = substr($req->path, strlen('/static/'));
        $root = realpath(Config::root() . '/public/static');
        $full = realpath($root . '/' . $rel);
        // only files inside the static folder; no dot-files, no folder listings
        if ($rel === '' || $full === false || !is_file($full) || !str_starts_with($full, $root . DIRECTORY_SEPARATOR)
            || preg_match('~(^|[\\\\/])\.~', substr($full, strlen($root)))) {
            throw new HttpException(404);
        }
        $ext = strtolower(pathinfo($full, PATHINFO_EXTENSION));
        return self::sendFile($req, $full, self::TYPES[$ext] ?? 'application/octet-stream');
    }

    public static function sendFile(Request $req, string $path, string $mime, ?string $etag = null, ?string $downloadName = null): Response
    {
        $size = (int) filesize($path);
        $mtime = (int) filemtime($path);
        $etag = '"' . ($etag ?: sprintf('%x-%x', $mtime, $size)) . '"';
        $resp = new Response('', 200, ['Content-Type' => $mime]);
        $resp->set('ETag', $etag);
        $resp->set('Last-Modified', gmdate('D, d M Y H:i:s \G\M\T', $mtime));
        $resp->set('Accept-Ranges', 'bytes');
        if ($downloadName !== null) {
            $ascii = preg_replace('/[^\x20-\x7e]|["\\\\]/', '_', $downloadName);
            $resp->set('Content-Disposition', "attachment; filename=\"{$ascii}\"; filename*=UTF-8''" . rawurlencode($downloadName));
        }
        $inm = $req->header('If-None-Match');
        $ims = $req->header('If-Modified-Since');
        if (($inm !== null && in_array($etag, array_map('trim', explode(',', $inm)), true))
            || ($inm === null && $ims !== null && strtotime($ims) !== false && strtotime($ims) >= $mtime)) {
            $resp->status = 304;
            return $resp;
        }
        $resp->file = $path;
        $range = $req->header('Range');
        if ($range !== null && preg_match('/^bytes=(\d*)-(\d*)$/', trim($range), $m) && ($m[1] !== '' || $m[2] !== '')) {
            if ($m[1] === '') {                       // the last N bytes
                $start = max(0, $size - (int) $m[2]);
                $end = $size - 1;
            } else {
                $start = (int) $m[1];
                $end = $m[2] === '' ? $size - 1 : min((int) $m[2], $size - 1);
            }
            if ($start > $end || $start >= $size) {
                $r = new Response('', 416, ['Content-Type' => $mime]);
                $r->set('Content-Range', "bytes */{$size}");
                return $r;
            }
            $resp->status = 206;
            $resp->range = [$start, $end];
            $resp->set('Content-Range', "bytes {$start}-{$end}/{$size}");
            $resp->set('Content-Length', (string) ($end - $start + 1));
            return $resp;
        }
        $resp->set('Content-Length', (string) $size);
        return $resp;
    }
}
