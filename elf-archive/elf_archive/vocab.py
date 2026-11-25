"""Controlled vocabularies. Single source of truth: migrations expand vocabulary macros
from this module so database CHECK constraints and application code cannot drift."""
from collections import OrderedDict

ENTITY_KINDS = ("person", "family", "place", "event", "organization", "source",
                "archive_item", "collection", "oral_history")
PRECISIONS = ("exact", "month", "year", "decade", "approximate", "range", "unknown")
PUBLICATION_STATUSES = ("draft", "submitted", "under_review", "needs_revision", "approved",
                        "published", "rejected", "withdrawn", "archived")
VISIBILITIES = ("public", "restricted", "private")
SUBMISSION_STATUSES = ("draft", "submitted", "under_review", "needs_revision", "approved",
                       "published", "rejected", "withdrawn", "superseded")
SUBMISSION_KINDS = ("person", "family", "place", "event", "source", "relationship", "correction", "organization",
                    "affiliation", "membership", "participation", "archive_item", "oral_history")
NAME_TYPES = ("preferred", "full", "original", "alternate_spelling", "transliteration",
              "alias", "nom_de_guerre", "nickname")
RELATIONSHIP_STATUSES = ("current", "historical", "uncertain", "disputed")
DIRECTED_RELATIONSHIPS = ("parent_of", "adoptive_parent_of", "step_parent_of", "guardian_of")
# (label when viewed from person A, label when viewed from person B)
RELATIONSHIP_TYPES = OrderedDict([
    ("parent_of", ("Parent of", "Child of")),
    ("adoptive_parent_of", ("Adoptive parent of", "Adopted child of")),
    ("step_parent_of", ("Step-parent of", "Step-child of")),
    ("guardian_of", ("Guardian of", "Ward of")),
    ("spouse_of", ("Spouse of", "Spouse of")),
    ("partner_of", ("Partner of", "Partner of")),
    ("sibling_of", ("Sibling of", "Sibling of")),
    ("other_documented", ("Documented connection with", "Documented connection with")),
])
EVIDENCE = OrderedDict([
    ("well_supported", ("Well supported", "Supported by reliable sources that agree.")),
    ("source_cited", ("Cited, not corroborated", "Supported by a cited source but not independently corroborated.")),
    ("testimony", ("Firsthand testimony", "Reported by a participant or eyewitness.")),
    ("family_recollection", ("Family recollection", "Remembered and reported by family members.")),
    ("oral_tradition", ("Oral tradition", "Passed down within a community.")),
    ("hypothesis", ("Research hypothesis", "A researcher's proposal that is not established.")),
    ("disputed", ("Disputed", "Sources or witnesses disagree.")),
    ("unverified", ("Unverified", "Supplied by a contributor and not yet assessed.")),
])
SOURCE_TYPES = ("book", "academic_publication", "newspaper_article", "official_record",
                "personal_letter", "photograph", "oral_history", "interview",
                "archival_collection", "family_document", "published_history",
                "organizational_publication", "map", "web_resource", "other")
RIGHTS_STATUSES = ("public_domain", "copyrighted_permission_granted", "copyrighted_permission_pending",
                   "licensed_specified_uses", "restricted_authorized", "private_embargoed",
                   "rights_unknown", "not_approved_public")
RIGHTS_LABELS = OrderedDict([
    ("public_domain", "Public domain (no copyright applies)"),
    ("copyrighted_permission_granted", "Copyrighted, and the rights holder has given permission"),
    ("copyrighted_permission_pending", "Copyrighted, permission requested but not yet given"),
    ("licensed_specified_uses", "Licensed for specified uses"),
    ("restricted_authorized", "Restricted to authorised researchers"),
    ("private_embargoed", "Private or embargoed: must not be shown publicly"),
    ("rights_unknown", "Rights unknown"),
    ("not_approved_public", "Not approved for public display"),
])
# Only these rights states allow an item to be shown publicly. Everything else stays restricted.
PUBLIC_RIGHTS = ("public_domain", "copyrighted_permission_granted", "licensed_specified_uses")
CONTRIBUTOR_RIGHTS = ("copyrighted_permission_granted", "public_domain", "copyrighted_permission_pending",
                      "licensed_specified_uses", "private_embargoed", "rights_unknown")
ITEM_TYPES = ("photograph", "scanned_document", "letter", "book_publication", "pamphlet_newsletter",
              "newspaper_clipping", "speech", "audio_recording", "video_recording", "transcript",
              "historical_map", "poster", "certificate_personal_papers", "other")
ITEM_TYPE_LABELS = OrderedDict([
    ("photograph", "Photograph"), ("scanned_document", "Scanned document"), ("letter", "Letter or correspondence"),
    ("book_publication", "Book or publication"), ("pamphlet_newsletter", "Pamphlet or newsletter"),
    ("newspaper_clipping", "Newspaper clipping"), ("speech", "Speech"), ("audio_recording", "Audio recording"),
    ("video_recording", "Video recording"), ("transcript", "Transcript"), ("historical_map", "Historical map"),
    ("poster", "Poster"), ("certificate_personal_papers", "Certificate or personal papers"), ("other", "Other"),
])
ACCESS_LEVELS = ("public", "restricted", "private", "embargoed")
CONSENT_TYPES = ("record", "store", "publish_recording", "publish_transcript", "publish_translation",
                 "use_excerpts", "research_access", "allow_download")
TRANSCRIPT_KINDS = ("verbatim", "edited", "translation", "machine_draft")
COORD_PRECISIONS = ("exact", "approximate", "region_centroid")
ROLES = ("editor", "moderator", "administrator", "researcher")
BASE_ROLE = "contributor"  # implicit for every active account; not stored

VOCAB = {
    "ENTITY_KINDS": ENTITY_KINDS, "PRECISIONS": PRECISIONS,
    "PUBLICATION_STATUSES": PUBLICATION_STATUSES, "VISIBILITIES": VISIBILITIES,
    "SUBMISSION_STATUSES": SUBMISSION_STATUSES, "SUBMISSION_KINDS": SUBMISSION_KINDS,
    "NAME_TYPES": NAME_TYPES, "RELATIONSHIP_STATUSES": RELATIONSHIP_STATUSES,
    "DIRECTED_RELATIONSHIPS": DIRECTED_RELATIONSHIPS,
    "RELATIONSHIP_TYPES": tuple(RELATIONSHIP_TYPES), "EVIDENCE": tuple(EVIDENCE),
    "SOURCE_TYPES": SOURCE_TYPES, "RIGHTS_STATUSES": RIGHTS_STATUSES, "PUBLIC_RIGHTS": PUBLIC_RIGHTS,
    "ITEM_TYPES": ITEM_TYPES,
    "ACCESS_LEVELS": ACCESS_LEVELS, "CONSENT_TYPES": CONSENT_TYPES,
    "TRANSCRIPT_KINDS": TRANSCRIPT_KINDS, "COORD_PRECISIONS": COORD_PRECISIONS, "ROLES": ROLES,
}

STATUS_LABELS = {
    "draft": ("Draft", "✎"), "submitted": ("Submitted", "➜"), "under_review": ("Under review", "⌕"),
    "needs_revision": ("Needs revision", "↺"), "approved": ("Approved", "✓"),
    "published": ("Published", "●"), "rejected": ("Rejected", "✕"), "withdrawn": ("Withdrawn", "—"),
    "superseded": ("Superseded", "⇄"), "archived": ("Archived", "▣"),
}
KIND_LABELS = {"person": "Person", "family": "Family", "place": "Place", "event": "Event",
               "source": "Source", "relationship": "Relationship", "correction": "Correction",
               "organization": "Organization", "archive_item": "Archive item",
               "collection": "Collection", "oral_history": "Oral history", "affiliation": "Affiliation",
               "membership": "Family membership", "participation": "Event participation"}
