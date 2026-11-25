<?php
declare(strict_types=1);

namespace Elf\Services;

/**
 * Name handling. Originals are stored untouched; `normalize` produces a separate search form.
 *
 * Normalization (search form only): Unicode NFKD, drop combining marks (Latin and Arabic diacritics), case-fold,
 * delete apostrophe-like marks so "Ghebre'ab" and "Ghebreab" meet, turn other punctuation into spaces.
 * Ge'ez (Ethiopic) letters are letters and survive intact. Normalization never decides that two names are the
 * same person; editors do.
 */
final class Names
{
    private const APOS = ["'", '’', '‘', 'ʼ', 'ʻ', 'ʿ', 'ʾ', '`', '´'];
    private const TATWEEL = 'ـ';

    public static function normalize(?string $text): string
    {
        if ($text === null || $text === '') {
            return '';
        }
        $t = \Normalizer::normalize($text, \Normalizer::FORM_KD);
        if ($t === false) {
            $t = $text;
        }
        $t = str_replace(array_merge(self::APOS, [self::TATWEEL]), '', $t);
        $t = preg_replace('/\p{Mn}/u', '', $t);
        $t = mb_convert_case($t, MB_CASE_FOLD, 'UTF-8');
        $t = preg_replace('/[^\p{L}\p{N}]/u', ' ', $t);
        return trim(preg_replace('/\s+/u', ' ', $t));
    }

    public static function tokens(?string $text): array
    {
        $n = self::normalize($text);
        return $n === '' ? [] : explode(' ', $n);
    }

    /** ASCII slug when possible; otherwise the permanent id (so non-Latin names never produce ''). */
    public static function slugify(?string $text, string $fallback): string
    {
        $t = \Normalizer::normalize($text ?? '', \Normalizer::FORM_KD) ?: ($text ?? '');
        $t = preg_replace('/\p{Mn}/u', '', $t);
        $t = str_replace(["'", '’'], '', $t);
        $t = strtolower(trim(preg_replace('/[^A-Za-z0-9]+/', '-', $t), '-'));
        $t = trim(substr($t, 0, 60), '-');
        return $t !== '' ? $t : $fallback;
    }
}
