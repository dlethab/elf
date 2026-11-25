<?php
declare(strict_types=1);

namespace Elf\Services;

/**
 * A port of Python's difflib.SequenceMatcher (Ratcliff/Obershelp) for strings, so duplicate detection scores
 * names exactly as the Python edition does. Works on Unicode characters. (Names are short, so difflib's
 * "autojunk" heuristic, which only applies to sequences of 200+ items, never matters here.)
 */
final class SequenceMatcher
{
    private array $a;
    private array $b;
    /** @var array<string,int[]> */
    private array $b2j = [];
    private ?array $blocks = null;

    public function __construct(string $a, string $b)
    {
        $this->a = mb_str_split($a, 1, 'UTF-8');
        $this->b = mb_str_split($b, 1, 'UTF-8');
        foreach ($this->b as $i => $ch) {
            $this->b2j[$ch][] = $i;
        }
    }

    private function longest(int $alo, int $ahi, int $blo, int $bhi): array
    {
        $besti = $alo;
        $bestj = $blo;
        $bestsize = 0;
        $j2len = [];
        for ($i = $alo; $i < $ahi; $i++) {
            $newj2len = [];
            foreach ($this->b2j[$this->a[$i]] ?? [] as $j) {
                if ($j < $blo) {
                    continue;
                }
                if ($j >= $bhi) {
                    break;
                }
                $k = $newj2len[$j] = ($j2len[$j - 1] ?? 0) + 1;
                if ($k > $bestsize) {
                    $besti = $i - $k + 1;
                    $bestj = $j - $k + 1;
                    $bestsize = $k;
                }
            }
            $j2len = $newj2len;
        }
        while ($besti > $alo && $bestj > $blo && $this->a[$besti - 1] === $this->b[$bestj - 1]) {
            $besti--;
            $bestj--;
            $bestsize++;
        }
        while ($besti + $bestsize < $ahi && $bestj + $bestsize < $bhi && $this->a[$besti + $bestsize] === $this->b[$bestj + $bestsize]) {
            $bestsize++;
        }
        return [$besti, $bestj, $bestsize];
    }

    public function matchingBlocks(): array
    {
        if ($this->blocks !== null) {
            return $this->blocks;
        }
        $la = count($this->a);
        $lb = count($this->b);
        $queue = [[0, $la, 0, $lb]];
        $blocks = [];
        while ($queue) {
            [$alo, $ahi, $blo, $bhi] = array_pop($queue);
            [$i, $j, $k] = $x = $this->longest($alo, $ahi, $blo, $bhi);
            if ($k) {
                $blocks[] = $x;
                if ($alo < $i && $blo < $j) {
                    $queue[] = [$alo, $i, $blo, $j];
                }
                if ($i + $k < $ahi && $j + $k < $bhi) {
                    $queue[] = [$i + $k, $ahi, $j + $k, $bhi];
                }
            }
        }
        usort($blocks, fn ($p, $q) => $p <=> $q);
        // collapse adjacent blocks
        $i1 = $j1 = $k1 = 0;
        $out = [];
        foreach ($blocks as [$i2, $j2, $k2]) {
            if ($i1 + $k1 === $i2 && $j1 + $k1 === $j2) {
                $k1 += $k2;
            } else {
                if ($k1) {
                    $out[] = [$i1, $j1, $k1];
                }
                [$i1, $j1, $k1] = [$i2, $j2, $k2];
            }
        }
        if ($k1) {
            $out[] = [$i1, $j1, $k1];
        }
        $out[] = [$la, $lb, 0];
        return $this->blocks = $out;
    }

    private static function calc(int $matches, int $length): float
    {
        return $length ? 2.0 * $matches / $length : 1.0;
    }

    public function ratio(): float
    {
        $m = array_sum(array_column($this->matchingBlocks(), 2));
        return self::calc($m, count($this->a) + count($this->b));
    }

    public function quickRatio(): float
    {
        $avail = [];
        $matches = 0;
        $fullbcount = array_count_values($this->b);
        foreach ($this->a as $ch) {
            $numb = $avail[$ch] ?? ($fullbcount[$ch] ?? 0);
            $avail[$ch] = $numb - 1;
            if ($numb > 0) {
                $matches++;
            }
        }
        return self::calc($matches, count($this->a) + count($this->b));
    }

    public function realQuickRatio(): float
    {
        $la = count($this->a);
        $lb = count($this->b);
        return self::calc(min($la, $lb), $la + $lb);
    }
}
