<?php
declare(strict_types=1);

namespace Elf\Services;

use Elf\Vocab;

/** The contribution forms: one specification per kind of record or link (the Python edition's SPECS, field for field). */
final class Specs
{
    public const REF_HELP = 'Start typing a name and choose from the list. Only published records can be chosen.';
    public const CONSENT_LABELS = [
        'record' => 'Being recorded', 'store' => 'The archive keeping the recording',
        'publish_recording' => 'Publishing the recording', 'publish_transcript' => 'Publishing the transcript',
        'publish_translation' => 'Publishing a translation', 'use_excerpts' => 'Quoting excerpts',
        'research_access' => 'Access by vetted researchers', 'allow_download' => 'Downloading and reuse',
    ];
    private static ?array $specs = null;
    private static ?Field $sources = null;

    private static function cap(string $s): string
    {
        $s = str_replace('_', ' ', $s);
        return ucfirst(strtolower($s));
    }

    public static function sourcesField(): Field
    {
        return self::$sources ??= new Field('sources', 'Supporting sources (one per line: Title | page or locator | URL)', 'sources', additive: true,
            help: "Each line becomes a separate source record, cited as 'unverified' until an editor assesses it.");
    }

    /** @return array<string, Field[]> */
    public static function all(): array
    {
        if (self::$specs !== null) {
            return self::$specs;
        }
        $F = fn (...$a) => new Field(...$a);
        $DATE_HELP = Dates::DATE_HELP;
        return self::$specs = [
            'person' => [
                $F('preferred_name', 'Preferred name', required: true),
                $F('full_name', 'Full name'),
                $F('original_name', 'Name in original script or language'),
                $F('original_name_lang', 'Language of that name (code, e.g. ti, ar, en)', max: 16),
                $F('aliases', 'Other spellings, transliterations, aliases (one per line)', 'lines', additive: true),
                $F('occupation', 'Occupation or civilian role', max: 300),
                $F('living_status', 'Living status', 'choice',
                    choices: [['unknown', 'Unknown'], ['deceased', 'Deceased'], ['living', 'Living']],
                    help: 'People recorded as living are kept private until an editor confirms consent.'),
                $F('birth', 'Birth', 'date', help: $DATE_HELP),
                $F('birth_place', 'Birthplace', 'ref', ref: 'place', help: 'Choose from published places; leave blank if unknown.'),
                $F('death', 'Death', 'date', help: $DATE_HELP),
                $F('death_place', 'Place of death', 'ref', ref: 'place'),
                $F('summary', 'Short summary', 'area', max: 1000, rows: 3),
                $F('biography', 'Biography and life history', 'area', max: 20000, rows: 10),
            ],
            'family' => [
                $F('display_name', 'Family name', required: true),
                $F('original_name', 'Name in original script or language'),
                $F('aliases', 'Other spellings (one per line)', 'lines', additive: true),
                $F('region_note', 'Regions or towns of association', max: 500),
                $F('summary', 'Short summary', 'area', max: 1000, rows: 3),
                $F('narrative', 'Family history', 'area', max: 20000, rows: 10),
            ],
            'place' => [
                $F('primary_name', 'Primary name', required: true),
                $F('original_name', 'Name in original script or language'),
                $F('aliases', 'Historical names and alternate spellings (one per line)', 'lines', additive: true),
                $F('place_type', 'Place type', 'taxon'),
                $F('country', 'Country', max: 100),
                $F('admin_region', 'Region / administrative area', max: 200),
                $F('latitude', 'Latitude (decimal degrees)', 'float',
                    help: 'Only enter coordinates you can source. Leave blank if unknown — never estimate silently.'),
                $F('longitude', 'Longitude (decimal degrees)', 'float'),
                $F('coord_precision', 'Coordinate precision', 'choice',
                    choices: array_merge([['', '—']], array_map(fn ($c) => [$c, self::cap($c)], Vocab::COORD_PRECISIONS)),
                    help: "Required when coordinates are given. 'Approximate' is shown to visitors as approximate."),
                $F('coord_note', 'Note on location uncertainty', 'area', max: 1000, rows: 2),
                $F('overview', 'Historical overview', 'area', max: 20000, rows: 8),
            ],
            'event' => [
                $F('title', 'Event title', required: true),
                $F('event_type', 'Event type', 'taxon'),
                $F('date', 'Date', 'date', help: $DATE_HELP),
                $F('place', 'Place', 'ref', ref: 'place', help: 'Choose from published places; leave blank if unknown.'),
                $F('summary', 'Short summary', 'area', max: 1000, rows: 3),
                $F('description', 'Detailed account', 'area', max: 20000, rows: 10),
            ],
            'source' => [
                $F('title', 'Title', required: true, max: 300),
                $F('source_type', 'Source type', 'choice', choices: array_map(fn ($s) => [$s, self::cap($s)], Vocab::SOURCE_TYPES)),
                $F('creator', 'Author or creator', max: 300),
                $F('publisher', 'Publisher'),
                $F('repository', 'Repository or archive'),
                $F('identifier', 'Identifier or catalogue number'),
                $F('pub_date_text', 'Publication or creation date (free text)', max: 100),
                $F('url', 'URL', 'url', max: 500),
                $F('language', 'Language', max: 50),
                $F('provenance', 'Provenance', 'area', max: 2000, rows: 3),
            ],
            'organization' => [
                $F('name', 'Organization name', required: true),
                $F('original_name', 'Name in original script or language'),
                $F('aliases', 'Other names, abbreviations and spellings (one per line)', 'lines', additive: true),
                $F('active', 'When it was active', 'date', help: $DATE_HELP),
                $F('description', 'Description and history', 'area', max: 20000, rows: 8),
            ],
            'relationship' => [
                $F('person_a', 'Person A', 'ref', ref: 'person', required: true, help: self::REF_HELP),
                $F('relationship_type', 'Relationship (A is … of B)', 'choice', required: true,
                    choices: array_map(fn ($k, $v) => [$k, $v[0]], array_keys(Vocab::RELATIONSHIP_TYPES), Vocab::RELATIONSHIP_TYPES)),
                $F('person_b', 'Person B', 'ref', ref: 'person', required: true, help: self::REF_HELP),
                $F('status', 'Status', 'choice', choices: array_map(fn ($s) => [$s, ucfirst($s)], Vocab::RELATIONSHIP_STATUSES)),
                $F('period', 'Dates, if relevant', 'date', help: $DATE_HELP),
                $F('notes', 'Explanation / notes', 'area', max: 2000, rows: 3),
            ],
            'affiliation' => [
                $F('person', 'Person', 'ref', ref: 'person', required: true, help: self::REF_HELP),
                $F('organization', 'Organization', 'ref', ref: 'organization', required: true, help: self::REF_HELP),
                $F('role', 'Role or position, if known', max: 200),
                $F('period', 'Dates of the affiliation', 'date', help: $DATE_HELP),
                $F('place', 'Place, if relevant', 'ref', ref: 'place'),
                $F('notes', 'Explanation / notes', 'area', max: 2000, rows: 3),
            ],
            'membership' => [
                $F('family', 'Family', 'ref', ref: 'family', required: true, help: self::REF_HELP),
                $F('person', 'Person', 'ref', ref: 'person', required: true, help: self::REF_HELP),
                $F('role_note', 'Place in the family, if documented (for example: eldest daughter)', max: 200),
                $F('period', 'Dates, if relevant', 'date', help: $DATE_HELP),
            ],
            'participation' => [
                $F('event', 'Event', 'ref', ref: 'event', required: true, help: self::REF_HELP),
                $F('person', 'Person', 'ref', ref: 'person', help: 'Choose a person or an organization.'),
                $F('organization', 'Organization', 'ref', ref: 'organization'),
                $F('role', 'Role in the event, if known', max: 200),
                $F('notes', 'Explanation / notes', 'area', max: 2000, rows: 3),
            ],
            'oral_history' => [
                $F('title', 'Title of the interview', required: true, max: 300),
                $F('interviewee', 'Interviewee (if they have a record in the archive)', 'ref', ref: 'person', help: self::REF_HELP),
                $F('interviewee_text', "Interviewee's name, if they have no record in the archive", max: 200),
                $F('interviewer_text', 'Interviewer', max: 200),
                $F('recorded', 'When it was recorded', 'date', help: $DATE_HELP),
                $F('recording_location_note', 'Where it was recorded (town or region only; never a home address)', max: 300),
                $F('language', 'Language of the interview', max: 100),
                $F('summary', 'Summary', 'area', max: 5000, rows: 4),
                $F('topics', 'Topics and keywords (one per line)', 'area', max: 2000, rows: 3),
                $F('related', 'People, families, places and events it concerns (one per line)', 'refs', max: 40,
                    help: "Type each record's name, or its name with the permanent ID in brackets. Only published records can be linked."),
                $F('transcript_text', 'Transcript', 'area', max: 300000, rows: 10,
                    help: 'Paste the transcript if there is one. Lines that start with a time such as [12:30] become links to that moment of the recording.'),
                $F('transcript_kind', 'What kind of transcript is it?', 'choice', choices: [
                    ['', '—'], ['verbatim', 'Verbatim (word for word)'], ['edited', 'Edited for reading'],
                    ['translation', 'A translation, not the original words'], ['machine_draft', 'Automatic transcription, not yet checked']]),
                $F('translation_language', 'Language of the translation', max: 100),
                $F('translation_text', 'Translation', 'area', max: 300000, rows: 8,
                    help: 'A translation is always kept separate from the original transcript and never replaces it.'),
                $F('translation_kind', 'Who made the translation?', 'choice', choices: [
                    ['', '—'], ['human_reviewed', 'A person, and it has been checked'], ['human_unreviewed', 'A person, not yet checked'],
                    ['machine_draft', 'Automatic translation, not yet checked']]),
                $F('consents', 'What the interviewee agreed to', 'consents'),
            ],
        ];
    }

    /** @return Field[] */
    public static function specFor(string $kind, bool $withSources = true): array
    {
        $fields = self::all()[$kind];
        if ($withSources && $kind !== 'source') {
            $fields[] = self::sourcesField();
        }
        return $fields;
    }

    public static function kinds(): array
    {
        return array_keys(self::all());
    }
}
