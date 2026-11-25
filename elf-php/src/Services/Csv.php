<?php
declare(strict_types=1);

namespace Elf\Services;

/** CSV reading and writing with the same rules as Python's csv module (RFC 4180 quoting, no backslash escapes). */
final class Csv
{
    /** @return array<int, array<int,string>> rows, quoted line breaks kept inside their cell */
    public static function read(string $text): array
    {
        $f = fopen('php://memory', 'r+');
        fwrite($f, $text);
        rewind($f);
        $rows = [];
        while (($row = fgetcsv($f, null, ',', '"', '')) !== false) {
            if ($row === [null]) {          // a blank line
                $rows[] = [];
                continue;
            }
            $rows[] = array_map(fn ($v) => (string) $v, $row);
        }
        fclose($f);
        return $rows;
    }

    /** @param array<int, array<int, mixed>> $rows */
    public static function write(array $rows, string $eol = "\r\n"): string
    {
        $f = fopen('php://memory', 'r+');
        foreach ($rows as $row) {
            fputcsv($f, array_map(fn ($v) => $v === null ? '' : (is_bool($v) ? ($v ? 'True' : 'False') : (is_float($v) ? Records::floatRepr($v) : (string) $v)), $row), ',', '"', '', $eol);
        }
        rewind($f);
        $out = (string) stream_get_contents($f);
        fclose($f);
        return $out;
    }
}
