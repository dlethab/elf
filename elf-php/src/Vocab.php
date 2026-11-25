<?php
declare(strict_types=1);

namespace Elf;

/**
 * Controlled vocabularies. Single source of truth: migrations expand vocabulary macros
 * from this class so database CHECK constraints and application code cannot drift.
 * (The same values as the Python edition, so both editions read the same database.)
 */
final class Vocab
{
    public const ENTITY_KINDS = ['person', 'family', 'place', 'event', 'organization', 'source',
        'archive_item', 'collection', 'oral_history'];
    public const PRECISIONS = ['exact', 'month', 'year', 'decade', 'approximate', 'range', 'unknown'];
    public const PUBLICATION_STATUSES = ['draft', 'submitted', 'under_review', 'needs_revision', 'approved',
        'published', 'rejected', 'withdrawn', 'archived'];
    public const VISIBILITIES = ['public', 'restricted', 'private'];
    public const SUBMISSION_STATUSES = ['draft', 'submitted', 'under_review', 'needs_revision', 'approved',
        'published', 'rejected', 'withdrawn', 'superseded'];
    public const SUBMISSION_KINDS = ['person', 'family', 'place', 'event', 'source', 'relationship', 'correction', 'organization',
        'affiliation', 'membership', 'participation', 'archive_item', 'oral_history'];
    public const NAME_TYPES = ['preferred', 'full', 'original', 'alternate_spelling', 'transliteration',
        'alias', 'nom_de_guerre', 'nickname'];
    public const RELATIONSHIP_STATUSES = ['current', 'historical', 'uncertain', 'disputed'];
    public const DIRECTED_RELATIONSHIPS = ['parent_of', 'adoptive_parent_of', 'step_parent_of', 'guardian_of'];
    /** (label when viewed from person A, label when viewed from person B) */
    public const RELATIONSHIP_TYPES = [
        'parent_of' => ['Parent of', 'Child of'],
        'adoptive_parent_of' => ['Adoptive parent of', 'Adopted child of'],
        'step_parent_of' => ['Step-parent of', 'Step-child of'],
        'guardian_of' => ['Guardian of', 'Ward of'],
        'spouse_of' => ['Spouse of', 'Spouse of'],
        'partner_of' => ['Partner of', 'Partner of'],
        'sibling_of' => ['Sibling of', 'Sibling of'],
        'other_documented' => ['Documented connection with', 'Documented connection with'],
    ];
    public const EVIDENCE = [
        'well_supported' => ['Well supported', 'Supported by reliable sources that agree.'],
        'source_cited' => ['Cited, not corroborated', 'Supported by a cited source but not independently corroborated.'],
        'testimony' => ['Firsthand testimony', 'Reported by a participant or eyewitness.'],
        'family_recollection' => ['Family recollection', 'Remembered and reported by family members.'],
        'oral_tradition' => ['Oral tradition', 'Passed down within a community.'],
        'hypothesis' => ['Research hypothesis', "A researcher's proposal that is not established."],
        'disputed' => ['Disputed', 'Sources or witnesses disagree.'],
        'unverified' => ['Unverified', 'Supplied by a contributor and not yet assessed.'],
    ];
    public const SOURCE_TYPES = ['book', 'academic_publication', 'newspaper_article', 'official_record',
        'personal_letter', 'photograph', 'oral_history', 'interview',
        'archival_collection', 'family_document', 'published_history',
        'organizational_publication', 'map', 'web_resource', 'other'];
    public const RIGHTS_STATUSES = ['public_domain', 'copyrighted_permission_granted', 'copyrighted_permission_pending',
        'licensed_specified_uses', 'restricted_authorized', 'private_embargoed',
        'rights_unknown', 'not_approved_public'];
    public const RIGHTS_LABELS = [
        'public_domain' => 'Public domain (no copyright applies)',
        'copyrighted_permission_granted' => 'Copyrighted, and the rights holder has given permission',
        'copyrighted_permission_pending' => 'Copyrighted, permission requested but not yet given',
        'licensed_specified_uses' => 'Licensed for specified uses',
        'restricted_authorized' => 'Restricted to authorised researchers',
        'private_embargoed' => 'Private or embargoed: must not be shown publicly',
        'rights_unknown' => 'Rights unknown',
        'not_approved_public' => 'Not approved for public display',
    ];
    /** Only these rights states allow an item to be shown publicly. Everything else stays restricted. */
    public const PUBLIC_RIGHTS = ['public_domain', 'copyrighted_permission_granted', 'licensed_specified_uses'];
    public const CONTRIBUTOR_RIGHTS = ['copyrighted_permission_granted', 'public_domain', 'copyrighted_permission_pending',
        'licensed_specified_uses', 'private_embargoed', 'rights_unknown'];
    public const ITEM_TYPES = ['photograph', 'scanned_document', 'letter', 'book_publication', 'pamphlet_newsletter',
        'newspaper_clipping', 'speech', 'audio_recording', 'video_recording', 'transcript',
        'historical_map', 'poster', 'certificate_personal_papers', 'other'];
    public const ITEM_TYPE_LABELS = [
        'photograph' => 'Photograph', 'scanned_document' => 'Scanned document', 'letter' => 'Letter or correspondence',
        'book_publication' => 'Book or publication', 'pamphlet_newsletter' => 'Pamphlet or newsletter',
        'newspaper_clipping' => 'Newspaper clipping', 'speech' => 'Speech', 'audio_recording' => 'Audio recording',
        'video_recording' => 'Video recording', 'transcript' => 'Transcript', 'historical_map' => 'Historical map',
        'poster' => 'Poster', 'certificate_personal_papers' => 'Certificate or personal papers', 'other' => 'Other',
    ];
    public const ACCESS_LEVELS = ['public', 'restricted', 'private', 'embargoed'];
    public const CONSENT_TYPES = ['record', 'store', 'publish_recording', 'publish_transcript', 'publish_translation',
        'use_excerpts', 'research_access', 'allow_download'];
    public const TRANSCRIPT_KINDS = ['verbatim', 'edited', 'translation', 'machine_draft'];
    public const COORD_PRECISIONS = ['exact', 'approximate', 'region_centroid'];
    public const ROLES = ['editor', 'moderator', 'administrator', 'researcher'];
    /** implicit for every active account; not stored */
    public const BASE_ROLE = 'contributor';

    public const STATUS_LABELS = [
        'draft' => ['Draft', '✎'], 'submitted' => ['Submitted', '➜'], 'under_review' => ['Under review', '⌕'],
        'needs_revision' => ['Needs revision', '↺'], 'approved' => ['Approved', '✓'],
        'published' => ['Published', '●'], 'rejected' => ['Rejected', '✕'], 'withdrawn' => ['Withdrawn', '—'],
        'superseded' => ['Superseded', '⇄'], 'archived' => ['Archived', '▣'],
    ];
    public const KIND_LABELS = ['person' => 'Person', 'family' => 'Family', 'place' => 'Place', 'event' => 'Event',
        'source' => 'Source', 'relationship' => 'Relationship', 'correction' => 'Correction',
        'organization' => 'Organization', 'archive_item' => 'Archive item',
        'collection' => 'Collection', 'oral_history' => 'Oral history', 'affiliation' => 'Affiliation',
        'membership' => 'Family membership', 'participation' => 'Event participation'];

    /** The vocabularies a migration may name as {{VOCAB:NAME}}. */
    public static function macro(string $name): array
    {
        return match ($name) {
            'ENTITY_KINDS' => self::ENTITY_KINDS, 'PRECISIONS' => self::PRECISIONS,
            'PUBLICATION_STATUSES' => self::PUBLICATION_STATUSES, 'VISIBILITIES' => self::VISIBILITIES,
            'SUBMISSION_STATUSES' => self::SUBMISSION_STATUSES, 'SUBMISSION_KINDS' => self::SUBMISSION_KINDS,
            'NAME_TYPES' => self::NAME_TYPES, 'RELATIONSHIP_STATUSES' => self::RELATIONSHIP_STATUSES,
            'DIRECTED_RELATIONSHIPS' => self::DIRECTED_RELATIONSHIPS,
            'RELATIONSHIP_TYPES' => array_keys(self::RELATIONSHIP_TYPES), 'EVIDENCE' => array_keys(self::EVIDENCE),
            'SOURCE_TYPES' => self::SOURCE_TYPES, 'RIGHTS_STATUSES' => self::RIGHTS_STATUSES, 'PUBLIC_RIGHTS' => self::PUBLIC_RIGHTS,
            'ITEM_TYPES' => self::ITEM_TYPES, 'ACCESS_LEVELS' => self::ACCESS_LEVELS, 'CONSENT_TYPES' => self::CONSENT_TYPES,
            'TRANSCRIPT_KINDS' => self::TRANSCRIPT_KINDS, 'COORD_PRECISIONS' => self::COORD_PRECISIONS, 'ROLES' => self::ROLES,
            default => throw new \InvalidArgumentException("Unknown vocabulary {$name}"),
        };
    }
}
