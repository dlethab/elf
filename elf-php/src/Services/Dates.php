<?php
declare(strict_types=1);

namespace Elf\Services;

/**
 * Historical dates with explicit uncertainty.
 *
 * A date is never "invented" to fill a gap: unknown stays unknown, a year stays a year, "c. 1952" stays approximate.
 * Partial ISO strings (YYYY, YYYY-MM, YYYY-MM-DD) are stored.
 *
 * Accepted input:  1952-03-14 | 1952-03 | 1952 | c. 1952 | circa 1952-03 | 1950s |
 *                  1950 to 1955 | 1950-03 to 1952 | (blank) | unknown
 */
final class Dates
{
    public const MIN_YEAR = 1000;
    public const MAX_YEAR = 2100;
    public const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
        'August', 'September', 'October', 'November', 'December'];
    public const DATE_HELP = 'Examples: 1952, 1952-03, 1952-03-14, c. 1952, 1950s, 1950 to 1955. Leave blank if unknown.';
    private const PART = '(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?';

    public static function unknown(): FuzzyDate
    {
        return new FuzzyDate();
    }

    private static function check(string $y, ?string $m, ?string $d): string
    {
        $year = (int) $y;
        if ($year < self::MIN_YEAR || $year > self::MAX_YEAR) {
            throw new DateError('Year must be between ' . self::MIN_YEAR . ' and ' . self::MAX_YEAR . '.');
        }
        if ($m !== null && $m !== '') {
            $month = (int) $m;
            if ($month < 1 || $month > 12) {
                throw new DateError('Month must be between 01 and 12.');
            }
            if ($d !== null && $d !== '' && !checkdate($month, (int) $d, $year)) {
                throw new DateError('That calendar date does not exist.');
            }
        }
        return implode('-', array_filter([$y, $m, $d], fn ($p) => $p !== null && $p !== ''));
    }

    /** Earliest and latest calendar day a partial ISO string can mean, as Y-m-d strings (comparable). */
    private static function bounds(string $s): array
    {
        $p = explode('-', $s);
        $y = (int) $p[0];
        if (count($p) === 1) {
            return [sprintf('%04d-01-01', $y), sprintf('%04d-12-31', $y)];
        }
        $m = (int) $p[1];
        if (count($p) === 2) {
            $last = (int) (new \DateTimeImmutable(sprintf('%04d-%02d-01', $y, $m)))->format('t');
            return [sprintf('%04d-%02d-01', $y, $m), sprintf('%04d-%02d-%02d', $y, $m, $last)];
        }
        $d = sprintf('%04d-%02d-%02d', $y, $m, (int) $p[2]);
        return [$d, $d];
    }

    private static function groups(array $m, int $from): array
    {
        return [$m[$from] ?? '', ($m[$from + 1] ?? '') !== '' ? $m[$from + 1] : null, ($m[$from + 2] ?? '') !== '' ? $m[$from + 2] : null];
    }

    public static function parse(?string $text): FuzzyDate
    {
        $t = trim($text ?? '');
        if ($t === '' || in_array(strtolower($t), ['unknown', '?'], true)) {
            return new FuzzyDate();
        }
        if (preg_match('/^(?:c\.?|ca\.?|circa|~)\s*' . self::PART . '$/i', $t, $m)) {
            return new FuzzyDate(self::check(...self::groups($m, 1)), null, 'approximate');
        }
        if (preg_match('/^(\d{3})0s$/', $t, $m)) {
            $base = (int) $m[1] * 10;
            self::check((string) $base, null, null);
            return new FuzzyDate((string) $base, (string) ($base + 9), 'decade');
        }
        if (preg_match('/^' . self::PART . '\s+to\s+' . self::PART . '$/i', $t, $m)) {
            $a = self::check(...self::groups($m, 1));
            $b = self::check(...self::groups($m, 4));
            if (self::bounds($a)[0] > self::bounds($b)[1]) {
                throw new DateError('The range ends before it starts.');
            }
            return new FuzzyDate($a, $b, 'range');
        }
        if (preg_match('/^' . self::PART . '$/', $t, $m)) {
            $iso = self::check(...self::groups($m, 1));
            return new FuzzyDate($iso, null, [1 => 'year', 2 => 'month', 3 => 'exact'][substr_count($iso, '-') + 1]);
        }
        throw new DateError('Use a form like 1952, 1952-03, 1952-03-14, c. 1952, 1950s, or 1950 to 1955.');
    }

    private static function one(string $s, array $months): string
    {
        $p = explode('-', $s);
        $y = (int) $p[0];
        if (count($p) === 1) {
            return (string) $y;
        }
        if (count($p) === 2) {
            return $months[(int) $p[1] - 1] . ' ' . $y;
        }
        return (int) $p[2] . ' ' . $months[(int) $p[1] - 1] . ' ' . $y;
    }

    /** Human display that preserves the uncertainty. Labels can be localised (see I18n::fdate). */
    public static function format(?string $start, ?string $end = null, ?string $precision = 'unknown',
                                  array $months = self::MONTHS, string $approx = 'c.', string $unknown = 'Unknown'): string
    {
        if ($precision === 'unknown' || $precision === null || !$start) {
            return $unknown;
        }
        if ($precision === 'approximate') {
            return $approx . ' ' . self::one($start, $months);
        }
        if ($precision === 'decade') {
            return $start . 's';
        }
        if ($precision === 'range') {
            return $end ? self::one($start, $months) . '–' . self::one($end, $months) : self::one($start, $months);
        }
        return self::one($start, $months);
    }

    /** Plain-language label so uncertainty is never conveyed by format alone. */
    public static function precisionNote(?string $precision): string
    {
        return [
            'exact' => 'exact date', 'month' => 'month known', 'year' => 'year known', 'decade' => 'decade only',
            'approximate' => 'approximate', 'range' => 'date range', 'unknown' => 'not documented',
        ][$precision] ?? (string) $precision;
    }

    /** [first_year, last_year] for filtering/sorting; null when unknown. */
    public static function yearSpan(?string $start, ?string $end, ?string $precision): ?array
    {
        if ($precision === 'unknown' || !$start) {
            return null;
        }
        return [(int) substr($start, 0, 4), (int) substr($end ?: $start, 0, 4)];
    }

    /** Inverse of parse(): the text a form should show so a round trip preserves the uncertainty. */
    public static function toInput(?string $start, ?string $end, ?string $precision): string
    {
        if ($precision === 'unknown' || !$start) {
            return '';
        }
        return match ($precision) {
            'approximate' => "c. {$start}",
            'decade' => "{$start}s",
            'range' => $end ? "{$start} to {$end}" : $start,
            default => $start,
        };
    }

    public static function columns(string $prefix, FuzzyDate $fd): array
    {
        return ["{$prefix}_start" => $fd->start, "{$prefix}_end" => $fd->end,
            "{$prefix}_precision" => $fd->precision, "{$prefix}_note" => $fd->note];
    }

    public static function fromRow(array $row, string $prefix): FuzzyDate
    {
        return new FuzzyDate($row["{$prefix}_start"], $row["{$prefix}_end"], $row["{$prefix}_precision"], $row["{$prefix}_note"]);
    }

    /** The stored {start, end, precision, note} form, as in submissions' proposed data. */
    public static function fromArray(?array $d): FuzzyDate
    {
        return $d ? new FuzzyDate($d['start'] ?? null, $d['end'] ?? null, $d['precision'] ?? 'unknown', $d['note'] ?? null) : new FuzzyDate();
    }
}
