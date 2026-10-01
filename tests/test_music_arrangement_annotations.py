"""Finished arrangements gain explicit annotations, never inherited state."""
from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

from tests.test_music_transitions import TransitionFixture
from matter_audio_core.contracts import canonical
from matter_audio_core.errors import AudioError
from score_matter.music import annotate_arrangement, arrange, execute, plan, show
from score_matter.music_validation import derived_annotation_level, validation_scope


class ArrangementAnnotationTests(TransitionFixture):
    def marking_request(self, plan_id, request_id="finished-mark", regions=None):
        return {"schema": "score-music-annotate-arrangement/v1", "request_id": request_id,
            "plan_id": plan_id, "source": "agent", "regions": regions if regions is not None else [
                {"id": "first", "segment_id": "a-repeat", "repeat_index": 0, "range": "full"},
                {"id": "edit", "segment_id": "a-repeat", "repeat_index": 1, "range": "body"},
                {"id": "last", "segment_id": "b", "repeat_index": 0, "range": "full"}]}

    def completed(self, request=None):
        prepared = arrange(self.store, self.request() if request is None else request)
        return prepared, execute(self.store, prepared["outputs"][0]["asset_id"])

    def test_full_and_body_ranges_map_exact_sources_and_only_the_completed_audio(self):
        prepared, result = self.completed()
        request = self.marking_request(prepared["outputs"][0]["asset_id"])
        code, marking = self.cli_request("annotate-arrangement", request)
        self.assertEqual(code, 0)
        document = show(self.store, marking["outputs"][0]["asset_id"])["document"]
        self.assertEqual(document["schema"], "score-music-arrangement-annotation/v1")
        self.assertEqual(document["timing"], {"mode": "unknown"})
        self.assertEqual(document["request"]["source"], "agent")
        self.assertEqual(document["audio"]["asset_id"], result["outputs"][0]["asset_id"])
        self.assertEqual(document["audio"]["digest"], result["outputs"][0]["digest"])
        self.assertEqual([(r["start_frame"], r["end_frame"]) for r in document["resolved_regions"]],
                         [(0, 6), (6, 9), (9, 15)])
        self.assertEqual([(r["source_start_frame"], r["source_end_frame"], r["contains_transition"])
                         for r in document["mappings"]], [(1, 7, False), (1, 4, False), (2, 8, True)])
        self.assertEqual([r["audio"]["asset_id"] for r in document["mappings"]],
                         [self.a["asset_id"], self.a["asset_id"], self.b["asset_id"]])
        self.assertFalse((self.store.root / "sessions.sqlite3").exists())
        self.assertEqual(self.cli_request("annotate-arrangement", request), (0, marking))
        self.assertEqual(marking["audio_model_calls"], 0)
        self.assertEqual({r["role"] for r in marking["outputs"][0]["parents"]}, {"annotates", "arrangement_plan"})

    def test_not_executed_pending_failed_and_wrong_receipt_never_trigger_execution(self):
        prepared = arrange(self.store, self.request())
        request = self.marking_request(prepared["outputs"][0]["asset_id"])
        count = self.counts()
        with self.assertRaises(AudioError) as caught:
            annotate_arrangement(self.store, request)
        self.assertEqual(caught.exception.code, "music_arrangement_not_completed")
        self.assertEqual(self.counts(), count)
        receipt_id = prepared["document"]["core_request"]["request_id"]
        self.store.transact(receipt_id, {"unrelated": "receipt"}, lambda publication: {})
        count = self.counts()
        with self.assertRaises(AudioError) as caught:
            annotate_arrangement(self.store, request)
        self.assertEqual(caught.exception.code, "music_binding_mismatch")
        self.assertEqual(self.counts(), count)
        for identifier, pending in (("pending-arrangement", True), ("failed-arrangement", False)):
            prepared = arrange(self.store, self.request(identifier))
            receipt_id = prepared["document"]["core_request"]["request_id"]
            def fail(publication):
                if pending:
                    raise OSError("Synthetic interrupted action")
                raise AudioError("fixture_failure", "Synthetic failed action")
            if pending:
                with self.assertRaises(OSError):
                    self.store.transact(receipt_id, {"resolution": prepared["document"]["core_resolution"]}, fail)
            else:
                self.store.transact(receipt_id, {"resolution": prepared["document"]["core_resolution"]}, fail)
            count = self.counts()
            with self.assertRaises(AudioError) as caught:
                annotate_arrangement(self.store, self.marking_request(prepared["outputs"][0]["asset_id"], identifier + "-mark"))
            self.assertEqual(caught.exception.code, "recovery_pending" if pending else "music_arrangement_not_completed")
            self.assertEqual(self.counts(), count)

    def test_explicit_marking_works_with_existing_trim_and_arrange_and_v1_has_no_mixed_ranges(self):
        prepared, _ = self.completed(self.legacy_request())
        marking = annotate_arrangement(self.store, self.marking_request(prepared["outputs"][0]["asset_id"]))
        self.assertTrue(all(not m["contains_transition"] for m in marking["document"]["mappings"]))
        self.assertEqual([(r["start_frame"], r["end_frame"]) for r in marking["document"]["resolved_regions"]],
                         [(0, 6), (6, 12), (12, 18)])
        trim = plan(self.store, {"schema": "score-music-plan/v1", "request_id": "finished-trim",
            "annotation_id": marking["outputs"][0]["asset_id"], "region_ids": ["edit"], "target": {"kind": "trim"}})
        trimmed = execute(self.store, trim["outputs"][0]["asset_id"])
        self.assertEqual(self.samples(trimmed), [100, 200, 300, 400, 500, 600])
        with self.assertRaises(AudioError):
            show(self.store, trimmed["outputs"][0]["asset_id"])
        repeated = arrange(self.store, {"schema": "score-music-arrange/v1", "request_id": "finished-repeat",
            "segments": [{"id": "selected", "annotation_id": marking["outputs"][0]["asset_id"], "region_id": "edit", "repeat": 2}]})
        self.assertEqual(self.samples(execute(self.store, repeated["outputs"][0]["asset_id"])), [100, 200, 300, 400, 500, 600] * 2)

    def test_invalid_occurrences_empty_bodies_and_unknown_fields_fail_before_claim(self):
        prepared, _ = self.completed()
        base = self.marking_request(prepared["outputs"][0]["asset_id"])
        cases = []
        for key, value in (("segment_id", "missing"), ("repeat_index", 2), ("repeat_index", True), ("range", "beats")):
            request = copy.deepcopy(base)
            request["regions"][0][key] = value
            cases.append(request)
        duplicate_id = copy.deepcopy(base)
        duplicate_id["regions"][1]["id"] = "first"
        cases.append(duplicate_id)
        duplicate_occurrence = copy.deepcopy(base)
        duplicate_occurrence["regions"][1]["repeat_index"] = 0
        cases.append(duplicate_occurrence)
        for key, value in (("timing", {"mode": "fixed"}), ("regions", []), ("plan_id", self.a["asset_id"])):
            cases.append({**base, key: value})
        count = self.counts()
        for request in cases:
            with self.subTest(request=request), self.assertRaises(AudioError):
                annotate_arrangement(self.store, request)
            self.assertEqual(self.counts(), count)
        prepared, _ = self.completed(self.request("empty-body", segments=[self.segment("a"), self.segment("middle"), self.segment("end")],
            transitions=[self.transition("a", 0, 3), self.transition("middle", 0, 3)]))
        count = self.counts()
        with self.assertRaises(AudioError) as caught:
            annotate_arrangement(self.store, self.marking_request(prepared["outputs"][0]["asset_id"], regions=[
                {"id": "middle", "segment_id": "middle", "repeat_index": 0, "range": "body"}]))
        self.assertEqual(caught.exception.code, "music_empty_body")
        self.assertEqual(self.counts(), count)

    def test_128_occurrences_are_supported_and_129_annotations_are_rejected(self):
        prepared, _ = self.completed(self.request(segments=[self.segment("a", repeat=64), self.segment("b", repeat=64)], transitions=[]))
        regions = [{"id": name + str(index), "segment_id": name, "repeat_index": index, "range": "body"}
                   for name in ("a", "b") for index in range(64)]
        request = self.marking_request(prepared["outputs"][0]["asset_id"], regions=regions)
        marking = annotate_arrangement(self.store, request)
        self.assertEqual(len(show(self.store, marking["outputs"][0]["asset_id"])["document"]["resolved_regions"]), 128)
        count = self.counts()
        with self.assertRaises(AudioError) as caught:
            annotate_arrangement(self.store, {**request, "request_id": "too-many-marks", "regions": regions + [regions[0]]})
        self.assertEqual(caught.exception.code, "invalid_request")
        self.assertEqual(self.counts(), count)

    def test_publication_replay_conflict_and_pending_do_not_create_another_annotation(self):
        prepared, _ = self.completed()
        request = self.marking_request(prepared["outputs"][0]["asset_id"])
        marking = annotate_arrangement(self.store, request)
        self.assertEqual(annotate_arrangement(self.store, request), marking)
        with self.assertRaises(AudioError) as caught:
            annotate_arrangement(self.store, {**request, "source": "user"})
        self.assertEqual(caught.exception.code, "request_conflict")
        publication = self.store._publish
        def interrupt(target, files):
            if target.parent.name == "objects":
                raise OSError("Synthetic annotation publication interruption")
            return publication(target, files)
        request = {**request, "request_id": "pending-mark"}
        with patch.object(self.store, "_publish", side_effect=interrupt), self.assertRaises(OSError):
            annotate_arrangement(self.store, request)
        count = self.counts()
        with self.assertRaises(AudioError) as caught:
            annotate_arrangement(self.store, request)
        self.assertEqual(caught.exception.code, "recovery_pending")
        self.assertEqual(self.counts(), count)

    def test_forged_published_mappings_receipt_and_refs_are_rejected_with_valid_parents(self):
        prepared, _ = self.completed()
        marking = annotate_arrangement(self.store, self.marking_request(prepared["outputs"][0]["asset_id"]))
        cases = [(('plan', 'asset_id'), self.a_mark['asset_id']), (('plan', 'digest', 'hex'), '0' * 64),
            (('execution', 'request_id'), 'other-action'), (('audio', 'asset_id'), self.a['asset_id']),
            (('mappings', 1, 'source_start_frame'), 2), (('mappings', 1, 'output_end_frame'), 10),
            (('mappings', 2, 'contains_transition'), False), (('resolved_regions', 1, 'end_frame'), 10),
            (('timing', 'mode'), 'free')]
        for index, (keys, value) in enumerate(cases):
            document = copy.deepcopy(marking["document"])
            target = document
            for key in keys[:-1]:
                target = target[key]
            target[keys[-1]] = value
            forged = self.forge(document, marking["outputs"][0], "forged-finished-" + str(index))
            count = self.counts()
            with self.subTest(keys=keys), self.assertRaises(AudioError) as caught:
                show(self.store, forged)
            self.assertEqual(caught.exception.code, "music_binding_mismatch")
            with self.assertRaises(AudioError) as caught:
                plan(self.store, {"schema": "score-music-plan/v1", "request_id": "must-not-plan",
                    "annotation_id": forged, "region_ids": ["edit"], "target": {"kind": "trim"}})
            self.assertEqual(caught.exception.code, "music_binding_mismatch")
            self.assertEqual(self.counts(), count)

    def derived(self, name, marking, other=None):
        segments = [{"id": "one", "annotation_id": marking["asset_id"], "region_id": "phrase", "repeat": 1}]
        if other is not None:
            segments.append({"id": "two", "annotation_id": other["asset_id"], "region_id": "phrase", "repeat": 1})
        prepared, _ = self.completed(self.request(name + "-plan", segments=segments, transitions=[]))
        request = self.marking_request(prepared["outputs"][0]["asset_id"], name + "-mark", [
            {"id": "phrase", "segment_id": "one", "repeat_index": 0, "range": "body"}])
        return prepared, annotate_arrangement(self.store, request)["outputs"][0], request

    def test_shared_dag_is_bounded_and_each_top_level_read_rechecks_integrity(self):
        left, right = self.a_mark, self.b_mark
        with validation_scope():
            for index in range(5):
                prepared, left, request = self.derived("diamond-" + str(index), left, right)
                right = annotate_arrangement(self.store, {**request, "request_id": "diamond-other-" + str(index)})["outputs"][0]
        with patch.object(self.store, "asset", wraps=self.store.asset) as reads:
            document = show(self.store, right["asset_id"])["document"]
        # A five-level diamond has only 10 derived annotations and 5 plans;
        # validate shared ancestors once per operation, not 2**depth times.
        self.assertLess(reads.call_count, 110)
        self.assertEqual(document["resolved_regions"][0]["end_frame"], 6)
        original = (self.store.root / self.a_mark["locator"]).read_bytes()
        (self.store.root / self.a_mark["locator"]).write_bytes(b"{}")
        with self.assertRaises(AudioError) as caught:
            show(self.store, right["asset_id"])
        self.assertEqual(caught.exception.code, "integrity_error")
        (self.store.root / self.a_mark["locator"]).write_bytes(original)
        self.assertEqual(show(self.store, right["asset_id"])["document"], document)

    def test_32_levels_are_readable_but_the_33rd_is_refused_before_claim(self):
        marking = self.a_mark
        # Fixture construction reuses already verified immutable ancestors;
        # acceptance below opens independent scopes and fully rereads the chain.
        with validation_scope():
            for index in range(32):
                _, marking, _ = self.derived("depth-" + str(index), marking)
        self.assertEqual(show(self.store, marking["asset_id"])["document"]["resolved_regions"][0]["end_frame"], 6)
        # A shallow cache hit cannot make the same 32-level subtree legal
        # beneath one additional derived annotation in a shared graph.
        with validation_scope():
            show(self.store, marking["asset_id"])
            with derived_annotation_level(), self.assertRaises(AudioError) as caught:
                show(self.store, marking["asset_id"])
            self.assertEqual(caught.exception.code, "music_annotation_ancestry")
        prepared, _ = self.completed(self.request("depth-over-plan", segments=[self.segment("one", marking)], transitions=[]))
        count = self.counts()
        with self.assertRaises(AudioError) as caught:
            annotate_arrangement(self.store, self.marking_request(prepared["outputs"][0]["asset_id"], "depth-over-mark", [
                {"id": "phrase", "segment_id": "one", "repeat_index": 0, "range": "body"}]))
        self.assertEqual(caught.exception.code, "music_annotation_ancestry")
        self.assertEqual(self.counts(), count)
        # Failure must not leak the active ancestry level into later operations.
        self.assertEqual(show(self.store, self.a_mark["asset_id"])["document"]["audio"]["asset_id"], self.a["asset_id"])

    def test_published_cycle_is_rejected_and_the_guard_is_cleared_after_failure(self):
        prepared, _ = self.completed()
        marking = annotate_arrangement(self.store, self.marking_request(prepared["outputs"][0]["asset_id"]))
        def publish(publication):
            annotation_doc, plan_doc = copy.deepcopy(marking["document"]), copy.deepcopy(prepared["document"])
            annotation_doc["request"]["plan_id"] = "a_" + publication.group_id + "_1"
            plan_doc["request"]["segments"][0]["annotation_id"] = "a_" + publication.group_id + "_0"
            for document, record in ((annotation_doc, marking["outputs"][0]), (plan_doc, prepared["outputs"][0])):
                publication.add(canonical(document), record["media"], role=record["role"], parents=record["parents"])
            return {}
        cyclic = self.store.transact("cyclic-fixture", {"fixture": "published-cycle"}, publish)
        with self.assertRaises(AudioError) as caught:
            show(self.store, cyclic["outputs"][0]["asset_id"])
        self.assertEqual(caught.exception.code, "music_annotation_ancestry")
        self.assertEqual(show(self.store, marking["outputs"][0]["asset_id"])["document"], marking["document"])


if __name__ == "__main__":
    unittest.main()
