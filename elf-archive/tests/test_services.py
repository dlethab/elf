import json
import sqlite3
import unittest

from elf_archive.services import dates, duplicates, entities, families, names, records, search, workflow
from elf_archive.services.workflow import PermissionDenied, WorkflowError
from tests.helpers import CONFIG, cu, make_db, make_user, publish, publish_new, submit_new

PERSON = {"preferred_name": "Testperson Alpha", "aliases": "Testperson Alfa\nT. Alpha", "summary": "FICTIONAL test record.",
          "birth": "c. 1930", "living_status": "deceased"}


class DatesAndNames(unittest.TestCase):
    def test_uncertainty_is_preserved(self):
        f = dates.parse("c. 1952")
        self.assertEqual(dates.format_date(f.start, f.end, f.precision), "c. 1952")
        self.assertEqual(dates.parse("").precision, "unknown")
        self.assertIsNone(dates.parse("").start)               # never a made-up date
        self.assertEqual(dates.format_date("1950", "1959", "decade"), "1950s")
        self.assertEqual(dates.format_date("1950", "1955", "range"), "1950–1955")

    def test_round_trip_through_form(self):
        for text in ("1952", "1952-03", "1952-03-14", "c. 1952", "1950s", "1950 to 1955", ""):
            f = dates.parse(text)
            self.assertEqual(dates.parse(dates.to_input(f.start, f.end, f.precision)), f)

    def test_invalid_dates_rejected(self):
        for bad in ("1952-02-30", "1955 to 1950", "03/04/1952", "1952-13", "0999"):
            with self.assertRaises(dates.DateError):
                dates.parse(bad)

    def test_name_normalisation_keeps_scripts(self):
        self.assertEqual(names.normalize("Ghebre'ab"), names.normalize("GHEBREAB"))
        self.assertEqual(names.normalize("Éric"), "eric")
        self.assertEqual(names.normalize("ገብረኣብ"), "ገብረኣብ")           # Ge'ez untouched
        self.assertEqual(names.normalize("مُحَمَّد"), "محمد")            # Arabic diacritics folded for search only
        self.assertEqual(names.slugify("ገብረኣብ", "per-abc"), "per-abc")  # no empty slugs for non-Latin names


class SchemaIntegrity(unittest.TestCase):
    def setUp(self):
        self.db = make_db()

    def test_precision_unknown_cannot_hold_a_date(self):
        eid, _, _ = entities.create_entity(self.db, "person", "Testperson X")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO people(entity_id, preferred_name, birth_start, birth_precision) VALUES (?,?,?,?)",
                            (eid, "Testperson X", "1950", "unknown"))

    def test_birthplace_must_be_a_place(self):
        pid, _, _ = entities.create_entity(self.db, "person", "Testperson A")
        other, _, _ = entities.create_entity(self.db, "person", "Testperson B")
        with self.assertRaises(sqlite3.IntegrityError):          # composite (id, kind) FK rejects a person as a place
            self.db.execute("INSERT INTO people(entity_id, preferred_name, birth_place_id) VALUES (?,?,?)", (pid, "Testperson A", other))

    def test_half_coordinates_rejected(self):
        eid, _, _ = entities.create_entity(self.db, "place", "Testville")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO places(entity_id, primary_name, latitude) VALUES (?,?,?)", (eid, "Testville", 10.0))

    def test_coordinates_require_precision(self):
        eid, _, _ = entities.create_entity(self.db, "place", "Testville")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO places(entity_id, primary_name, latitude, longitude) VALUES (?,?,?,?)", (eid, "Testville", 1.0, 2.0))

    def test_audit_and_revisions_are_append_only(self):
        self.db.execute("INSERT INTO audit_logs(action) VALUES ('x')")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("DELETE FROM audit_logs")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE audit_logs SET action='y'")
        eid, _, _ = entities.create_entity(self.db, "family", "Testfamily")
        self.db.execute("INSERT INTO families(entity_id, display_name) VALUES (?,?)", (eid, "Testfamily"))
        entities.add_revision(self.db, eid, None, "created")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("DELETE FROM revisions")

    def test_symmetric_relationship_stored_once(self):
        a, _, _ = entities.create_entity(self.db, "person", "Testperson A")
        b, _, _ = entities.create_entity(self.db, "person", "Testperson B")
        with self.assertRaises(sqlite3.IntegrityError):           # spouse_of must be stored with smaller id first
            self.db.execute("INSERT INTO relationships(person_a_id, person_b_id, relationship_type) VALUES (?,?, 'spouse_of')", (max(a, b), min(a, b)))
        self.db.execute("INSERT INTO relationships(person_a_id, person_b_id, relationship_type) VALUES (?,?, 'spouse_of')", (min(a, b), max(a, b)))

    def test_event_participant_exactly_one_kind(self):
        ev, _, _ = entities.create_entity(self.db, "event", "Testevent")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO event_participants(event_id) VALUES (?)", (ev,))


class WorkflowRules(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        self.contrib = make_user(self.db, "contrib")
        self.editor = make_user(self.db, "editor1", ["editor"])
        self.editor2 = make_user(self.db, "editor2", ["editor"])

    def test_nothing_exists_until_published(self):
        sid = submit_new(self.db, self.contrib, "person", PERSON)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM entities WHERE kind='person'").fetchone()[0], 0)
        workflow.transition(self.db, self.editor, sid, "under_review", config=CONFIG)
        workflow.transition(self.db, self.editor, sid, "approved", message="ok", config=CONFIG)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM entities WHERE kind='person'").fetchone()[0], 0)  # approved ≠ published
        workflow.transition(self.db, self.editor, sid, "published", config=CONFIG)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM entities WHERE kind='person' AND publication_status='published'").fetchone()[0], 1)

    def test_contributor_cannot_review_or_publish(self):
        sid = submit_new(self.db, self.contrib, "person", PERSON)
        for to in ("under_review", "approved", "published", "rejected"):
            with self.assertRaises((PermissionDenied, WorkflowError)):
                workflow.transition(self.db, self.contrib, sid, to, message="x", config=CONFIG)
        other = make_user(self.db, "other")
        with self.assertRaises(PermissionDenied):                      # nor can another contributor withdraw it
            workflow.transition(self.db, other, sid, "withdrawn", config=CONFIG)

    def test_moderator_cannot_review_archive_submissions(self):
        mod = make_user(self.db, "mod", ["moderator"])
        sid = submit_new(self.db, self.contrib, "person", PERSON)
        with self.assertRaises(PermissionDenied):
            workflow.transition(self.db, mod, sid, "under_review", config=CONFIG)
        self.assertIsNone(workflow.get_for_user(self.db, mod, sid))

    def test_cannot_skip_states(self):
        clean, _ = records.validate(self.db, "person", PERSON)
        sid = workflow.create(self.db, self.contrib, "person", clean, config=CONFIG)       # draft
        with self.assertRaises(WorkflowError):
            workflow.transition(self.db, self.editor, sid, "published", config=CONFIG)
        workflow.transition(self.db, self.contrib, sid, "submitted", config=CONFIG)
        with self.assertRaises(WorkflowError):                          # submitted → published is illegal
            workflow.transition(self.db, self.editor, sid, "published", config=CONFIG)

    def test_self_review_blocked_by_default(self):
        sid = submit_new(self.db, self.editor, "person", PERSON)
        with self.assertRaises(PermissionDenied):
            workflow.transition(self.db, self.editor, sid, "under_review", config=CONFIG)
        workflow.transition(self.db, self.editor2, sid, "under_review", config=CONFIG)   # a different editor can

    def test_revision_cycle_and_reason_required(self):
        sid = submit_new(self.db, self.contrib, "person", PERSON)
        workflow.transition(self.db, self.editor, sid, "under_review", config=CONFIG)
        with self.assertRaises(WorkflowError):
            workflow.transition(self.db, self.editor, sid, "needs_revision", config=CONFIG)
        workflow.transition(self.db, self.editor, sid, "needs_revision", message="Please cite a source.",
                            internal_note="suspect duplicate", config=CONFIG)
        workflow.update_draft(self.db, self.contrib, sid, json.loads(self.db.execute("SELECT proposed_data FROM submissions").fetchone()[0]))
        workflow.transition(self.db, self.contrib, sid, "submitted", config=CONFIG)
        shown = " ".join((e["message"] or "") for e in workflow.visible_events(self.db, self.contrib, sid))
        self.assertIn("Please cite a source.", shown)
        self.assertNotIn("Internal note", shown)
        staff = " ".join((e["message"] or "") for e in workflow.visible_events(self.db, self.editor, sid, as_staff=True))
        self.assertIn("Internal note", staff)

    def test_unverified_email_cannot_submit(self):
        u = make_user(self.db, "unverified", verified=False)
        with self.assertRaises(PermissionDenied):
            workflow.authorize_new(self.db, u, "person", config=CONFIG)

    def test_published_record_has_revision_audit_and_is_searchable_by_alias(self):
        e = publish_new(self.db, self.contrib, self.editor, "person", PERSON)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM revisions WHERE entity_id=?", (e["id"],)).fetchone()[0], 1)
        self.assertTrue(self.db.execute("SELECT 1 FROM audit_logs WHERE action='record.published'").fetchone())
        r = search.search(self.db, "alfa")                               # alias, partial
        self.assertEqual([x["public_id"] for x in r["results"]], [e["public_id"]])
        self.assertIn("Testperson Alfa", r["results"][0]["matched_name"])
        self.assertEqual(search.search(self.db, "testperson")["total"], 1)  # one record, not one per alias

    def test_living_person_is_restricted_and_unsearchable_until_consent(self):
        raw = dict(PERSON, preferred_name="Testperson Living", aliases="", living_status="living")
        e = publish_new(self.db, self.contrib, self.editor, "person", raw)
        self.assertEqual(e["visibility"], "restricted")
        self.assertEqual(search.search(self.db, "Living")["total"], 0)
        self.assertIsNone(entities.resolve_public(self.db, "person", e["slug"]))
        raw2 = dict(PERSON, preferred_name="Testperson Consented", aliases="", living_status="living")
        e2 = publish_new(self.db, self.contrib, self.editor, "person", raw2, consent=True)
        self.assertEqual(e2["visibility"], "public")

    def _correct(self, entity, raw):
        clean, errs = records.validate(self.db, "person", raw)
        self.assertFalse(errs)
        changes = records.changed_fields(self.db, "person", entity["id"], clean)
        target, _ = workflow.authorize_new(self.db, self.contrib, "correction", target_public_id=entity["public_id"], config=CONFIG)
        sid = workflow.create(self.db, self.contrib, "correction", {"changes": changes}, target=target, config=CONFIG)
        workflow.transition(self.db, self.contrib, sid, "submitted", config=CONFIG)
        publish(self.db, self.editor, sid)
        return changes

    def test_correction_is_additive_to_history(self):
        e = publish_new(self.db, self.contrib, self.editor, "person", PERSON)
        changes = self._correct(e, dict(PERSON, preferred_name="Testperson Alpha-Renamed", aliases=""))
        self.assertEqual(set(changes), {"preferred_name"})
        self.assertEqual(entities.title_of(self.db, e["id"]), "Testperson Alpha-Renamed")
        self.assertEqual(search.search(self.db, "Alpha-Renamed")["total"], 1)
        self.assertEqual(search.search(self.db, "testperson alpha")["total"], 1)     # old spelling still finds it
        self.assertEqual(entities.latest_revision_number(self.db, e["id"]), 2)
        self.assertEqual(entities.get(self.db, e["id"])["slug"], e["slug"])          # URL is stable

    def test_correction_to_living_hides_public_record(self):
        e = publish_new(self.db, self.contrib, self.editor, "person", PERSON)
        self._correct(e, dict(PERSON, aliases="", living_status="living"))
        self.assertEqual(entities.get(self.db, e["id"])["visibility"], "restricted")
        self.assertEqual(search.search(self.db, "Alpha")["total"], 0)

    def test_correction_of_private_record_is_indistinguishable_from_missing(self):
        e = publish_new(self.db, self.contrib, self.editor, "person", dict(PERSON, living_status="living"))
        with self.assertRaises(WorkflowError) as a:
            workflow.authorize_new(self.db, self.contrib, "correction", target_public_id=e["public_id"], config=CONFIG)
        with self.assertRaises(WorkflowError) as b:
            workflow.authorize_new(self.db, self.contrib, "correction", target_public_id="per-doesnotexist", config=CONFIG)
        self.assertEqual(str(a.exception), str(b.exception))

    def test_failed_publish_rolls_back_everything(self):
        place = publish_new(self.db, self.contrib, self.editor, "place", {"primary_name": "Testville"})
        sid = submit_new(self.db, self.contrib, "person", dict(PERSON, birth_place=place["public_id"], aliases=""))
        workflow.transition(self.db, self.editor, sid, "under_review", config=CONFIG)
        workflow.transition(self.db, self.editor, sid, "approved", message="ok", config=CONFIG)
        entities.set_state(self.db, place["id"], visibility="restricted", actor_id=self.editor.id)   # place withdrawn meanwhile
        with self.assertRaises(WorkflowError):
            workflow.transition(self.db, self.editor, sid, "published", config=CONFIG)
        self.assertEqual(self.db.execute("SELECT status FROM submissions WHERE id=?", (sid,)).fetchone()[0], "approved")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM entities WHERE kind='person'").fetchone()[0], 0)

    def test_sources_are_shared_records_with_claim_level_citations(self):
        src = "Test Source Book (FICTIONAL) | p. 12 | https://example.test/book"
        a = publish_new(self.db, self.contrib, self.editor, "person", dict(PERSON, aliases="", sources=src))
        b = publish_new(self.db, self.contrib, self.editor, "person",
                        {"preferred_name": "Testperson Beta", "sources": "Test Source Book (FICTIONAL) | p. 40 | https://example.test/book"})
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 1)        # one source…
        rows = self.db.execute("SELECT target_id, locator, evidence_status FROM citations ORDER BY id").fetchall()
        self.assertEqual([(r[0], r[1], r[2]) for r in rows],                                     # …two distinct citations
                         [(a["id"], "p. 12", "unverified"), (b["id"], "p. 40", "unverified")])


class RelationshipsAndFamilies(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        self.contrib = make_user(self.db, "contrib")
        self.rep = make_user(self.db, "rep")
        self.editor = make_user(self.db, "editor1", ["editor"])
        self.a = publish_new(self.db, self.contrib, self.editor, "person", {"preferred_name": "Testperson Parent"})
        self.b = publish_new(self.db, self.contrib, self.editor, "person", {"preferred_name": "Testperson Child"})
        self.fam = publish_new(self.db, self.contrib, self.editor, "family", {"display_name": "Testfamily"})
        self.rel = {"person_a": self.a["public_id"], "person_b": self.b["public_id"], "relationship_type": "parent_of", "notes": "FICTIONAL"}

    def test_plain_contributor_cannot_propose_relationship(self):
        with self.assertRaises(PermissionDenied):
            workflow.authorize_new(self.db, self.contrib, "relationship", config=CONFIG)
        with self.assertRaises(PermissionDenied):
            workflow.authorize_new(self.db, self.contrib, "relationship", family_public_id=self.fam["public_id"], config=CONFIG)

    def test_rep_can_propose_but_never_publish_and_grant_is_revocable(self):
        families.grant(self.db, self.editor.id, "rep", self.fam["id"])
        rep = cu(self.db, self.rep.id)
        _, fam = workflow.authorize_new(self.db, rep, "relationship", family_public_id=self.fam["public_id"], config=CONFIG)
        clean, errs = records.validate(self.db, "relationship", self.rel)
        self.assertFalse(errs)
        sid = workflow.create(self.db, rep, "relationship", clean, family=fam, config=CONFIG)
        workflow.transition(self.db, rep, sid, "submitted", config=CONFIG)
        for to in ("under_review", "approved", "published"):
            with self.assertRaises((PermissionDenied, WorkflowError)):
                workflow.transition(self.db, rep, sid, to, message="x", config=CONFIG)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM relationships").fetchone()[0], 0)
        publish(self.db, self.editor, sid)
        row = self.db.execute("SELECT * FROM relationships").fetchone()
        self.assertEqual((row["relationship_type"], row["visibility"]), ("parent_of", "public"))
        g = families.active_grant(self.db, self.rep.id, self.fam["id"])
        families.revoke(self.db, self.editor.id, g["id"])
        with self.assertRaises(PermissionDenied):
            workflow.authorize_new(self.db, rep, "relationship", family_public_id=self.fam["public_id"], config=CONFIG)

    def test_grant_for_one_family_does_not_cover_another(self):
        other = publish_new(self.db, self.contrib, self.editor, "family", {"display_name": "Testfamily Two"})
        families.grant(self.db, self.editor.id, "rep", self.fam["id"])
        with self.assertRaises(PermissionDenied):
            workflow.authorize_new(self.db, cu(self.db, self.rep.id), "relationship", family_public_id=other["public_id"], config=CONFIG)

    def test_duplicate_and_self_relationships_rejected(self):
        _, errs = records.validate(self.db, "relationship", dict(self.rel, person_b=self.a["public_id"]))
        self.assertIn("person_b", errs)
        records.apply_relationship(self.db, records.validate(self.db, "relationship", self.rel)[0], actor_id=self.editor.id, submission_id=None)
        _, errs = records.validate(self.db, "relationship", self.rel)
        self.assertIn("relationship_type", errs)

    def test_unpublished_person_cannot_be_referenced(self):
        _, errs = records.validate(self.db, "relationship", dict(self.rel, person_b="per-nonexistent"))
        self.assertIn("person_b", errs)


class DuplicatesAndSlugs(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        self.c = make_user(self.db, "contrib")
        self.e = make_user(self.db, "editor1", ["editor"])

    def test_similar_names_are_candidates_not_merges(self):
        a = publish_new(self.db, self.c, self.e, "person", {"preferred_name": "Testperson Hamed", "birth": "1930"})
        c = duplicates.find_person_candidates(self.db, ["Testperson Hamid"], birth_year=1930)
        self.assertEqual(c[0]["public_id"], a["public_id"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM entities WHERE kind='person'").fetchone()[0], 1)

    def test_slug_change_keeps_old_url_resolving(self):
        a = publish_new(self.db, self.c, self.e, "person", {"preferred_name": "Testperson Slug"})
        entities.change_slug(self.db, a["id"], "testperson-new-slug", self.e.id)
        kind, e = entities.resolve_public(self.db, "person", a["slug"])
        self.assertEqual((kind, e["slug"]), ("redirect", "testperson-new-slug"))
        self.assertEqual(entities.resolve_public(self.db, "person", "testperson-new-slug")[0], "ok")

    def test_non_latin_name_gets_permanent_id_slug(self):
        a = publish_new(self.db, self.c, self.e, "person", {"preferred_name": "ተስት"})
        self.assertEqual(a["slug"], a["public_id"])


if __name__ == "__main__":
    unittest.main()
