<?php
declare(strict_types=1);

namespace Elf\Services;

use Elf\Config;

/**
 * File storage for uploaded media. Files are stored under random keys OUTSIDE any web-served folder and are never
 * executed or served directly: every download goes through the access-checking /media route.
 * The layout (root/<first two characters>/<key>) is the Python edition's, so both can share one media folder.
 */
final class Storage
{
    private const KEY = '/^[A-Za-z0-9_-]{24,64}$/';
    public readonly string $root;

    public function __construct(string $root)
    {
        $this->root = rtrim(str_replace('\\', '/', $root), '/');
    }

    public static function fromConfig(array $config): self
    {
        return new self(Config::path($config['MEDIA_ROOT']));
    }

    public static function newKey(): string
    {
        return Util::tokenUrlsafe(24);          // 32 URL-safe characters; unguessable
    }

    public function path(string $key): string
    {
        if (!preg_match(self::KEY, $key)) {
            throw new \InvalidArgumentException('invalid storage key');
        }
        return $this->root . '/' . substr($key, 0, 2) . '/' . $key;
    }

    public function put(string $key, string $data): void
    {
        $path = $this->path($key);
        if (!is_dir(dirname($path))) {
            mkdir(dirname($path), 0770, true);
        }
        $tmp = $path . '.part';
        file_put_contents($tmp, $data);
        rename($tmp, $path);                    // atomic: a half-written file is never visible
    }

    /** Copy a file (e.g. a PHP upload) to storage without loading large audio and video into memory. */
    public function putFile(string $key, string $source): void
    {
        $path = $this->path($key);
        if (!is_dir(dirname($path))) {
            mkdir(dirname($path), 0770, true);
        }
        $tmp = $path . '.part';
        if (!copy($source, $tmp)) {
            throw new \RuntimeException('Could not store the file.');
        }
        rename($tmp, $path);
    }

    public function get(string $key): string
    {
        return (string) file_get_contents($this->path($key));
    }

    public function exists(string $key): bool
    {
        return is_file($this->path($key));
    }

    public function delete(string $key): void
    {
        $p = $this->path($key);
        if (is_file($p)) {
            @unlink($p);
        }
    }
}
