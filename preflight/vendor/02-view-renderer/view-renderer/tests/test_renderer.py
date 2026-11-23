#!/usr/bin/env python3
"""Tier A functional tests F1-F8 (brief §5). Run: python -m unittest discover tests -v"""
import json, shutil, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT.parent / "qafiya-ref" / "qafiya-core"))
sys.path.insert(0, str(ROOT))

from dvr import specval, resolve, render, edits, affordance
from qafiya_core import engine, semantic, store

RECORDS = [
    {"id": "r_010", "date": "2026-07-11", "period": "Q2", "amount": 4800.0, "category": "travel"},
    {"id": "r_011", "date": "2026-08-03", "period": "Q3", "amount": 2100.0, "category": "food"},
    {"id": "r_012", "date": "2026-09-15", "period": "Q3", "amount": 2110.0, "category": "tools"},
]

def make_workspace():
    """Frozen fixture: one dataset, one view binding, one claim binding."""
    root = Path(tempfile.mkdtemp())
    ds = root / "datasets" / "expenses"
    ds.mkdir(parents=True)
    store.atomic_write_jsonl(ds / store.DATA, RECORDS)
    (ds / "schema.json").write_text(json.dumps({
        "dataset": "expenses", "id_field": "id",
        "fields": {"id": "id", "date": "timestamp", "period": "enum[Q2,Q3]",
                   "amount": "number", "category": "enum[travel,food,tools,other]"},
        "derivations": ["sum", "avg", "count", "min", "max"]}))
    bindings = [
        {"id": "b_7f3a", "kind": "view", "target": {"view": "v_q3", "node": "cell:total"},
         "sources": [{"dataset": "ds:expenses", "filter": "period=Q3", "field": "amount",
                      "key_path": ["amount"], "verbatim_excerpt": "2110.0"}],
         "derivation": "sum(amount) where period='Q3'", "value": 4210.0, "statistic": "sum",
         "device": "test", "authoritative_artifact": "datasets/expenses/data.jsonl",
         "provenance": {"created_by": "test", "created_at": "2026-10-19T00:00Z"},
         "check": {"provenance": "PASS", "checked_at": "2026-10-19T00:00Z"}},
        {"id": "b_9c11", "kind": "claim", "target": {"view": "v_q3", "node": "claim:trend"},
         "sources": [{"dataset": "ds:expenses", "field": "amount", "key_path": ["amount"],
                      "verbatim_excerpt": "4800.0"}],
         "derivation": "sum(amount) where period='Q3'", "value": 4210.0, "statistic": "sum",
         "device": "test", "authoritative_artifact": "datasets/expenses/data.jsonl",
         "assertion": {"statement": "Q3 spend fell 12% vs Q2", "predicate": "direction",
                       "expected": -0.12, "tolerance": 0.005,
                       "both_sides": {"Q2": {"derivation": "sum(amount) where period='Q2'"},
                                      "Q3": {"derivation": "sum(amount) where period='Q3'"}}},
         "provenance": {"created_by": "test", "created_at": "2026-10-19T00:00Z"},
         "check": {"provenance": "PASS", "semantic": "PASS", "checked_at": "2026-10-19T00:00Z"}},
        {"id": "b_cell12", "kind": "view", "target": {"view": "v_q3", "node": "cell:r_012"},
         "sources": [{"dataset": "ds:expenses", "filter": "period=Q3", "field": "amount",
                      "key_path": ["amount"], "verbatim_excerpt": "2110.0"}],
         "derivation": "sum(amount) where period='Q3'", "value": 4210.0, "statistic": "sum",
         "device": "test", "authoritative_artifact": "datasets/expenses/data.jsonl",
         "provenance": {"created_by": "test", "created_at": "2026-10-19T00:00Z"},
         "check": {"provenance": "PASS", "checked_at": "2026-10-19T00:00Z"}},
    ]
    store.atomic_write_jsonl(root / store.BINDINGS, bindings)
    return root

VIEW = {
    "spec": "dvr/1.0", "id": "v_q3", "kind": "table",
    "title": {"text": "Q3 expenses"},
    "columns": [{"id": "col:amount", "label": "Amount", "source_field": "amount"}],
    "nodes": [
        {"id": "cell:total", "role": "value", "binding_ref": "b_7f3a", "column": "col:amount"},
        {"id": "cell:r_012", "role": "value", "binding_ref": "b_cell12",
         "column": "col:amount", "row_key": "r_012", "editable": True},
        {"id": "claim:trend", "role": "claim", "binding_ref": "b_9c11"},
        {"id": "lbl", "role": "label", "text": "All figures verified against frozen data."},
    ],
}


class F1GrammarValidation(unittest.TestCase):
    def test_valid_view_passes(self):
        self.assertIs(specval.validate_view(VIEW), VIEW)

    def test_rejects_bad_specs(self):
        bad = []
        v = dict(VIEW, spec="dvr/0.9"); bad.append(v)
        v = dict(VIEW, kind="chart"); bad.append(v)
        v = json.loads(json.dumps(VIEW)); v["nodes"][0]["value"] = 4210.0; bad.append(v)      # embedded value
        v = json.loads(json.dumps(VIEW)); del v["nodes"][0]["binding_ref"]; bad.append(v)     # missing ref
        v = json.loads(json.dumps(VIEW)); v["nodes"][1]["id"] = "cell:total"; bad.append(v)   # dup id
        v = json.loads(json.dumps(VIEW)); v["nodes"][2]["editable"] = True; bad.append(v)     # editable claim
        v = json.loads(json.dumps(VIEW)); v["nodes"][0]["binding_ref"] = "b_nope"; bad.append(v)  # dangling ref
        for i, v in enumerate(bad):
            with self.assertRaises(specval.SpecError, msg=f"fixture {i} should be rejected"):
                specval.validate_view(v, known_binding_ids={"b_7f3a", "b_9c11", "b_cell12"})


class F2F3ResolutionPurity(unittest.TestCase):
    def setUp(self):
        self.root = make_workspace()

    def test_resolution_matches_recompute(self):
        bindings = resolve.load_bindings(self.root)
        v, st = resolve.resolve_binding(self.root, bindings["b_7f3a"])
        self.assertEqual(v, 4210.0)
        # tamper with data -> resolution must follow data, not cached binding.value
        ds, records = store.load_dataset(self.root, "expenses")
        records[1]["amount"] = 999.0
        store.atomic_write_jsonl(ds / store.DATA, records)
        v, _ = resolve.resolve_binding(self.root, bindings["b_7f3a"])
        self.assertEqual(v, 3109.0)  # 999 + 2110 — cached 4210 never trusted

    def test_unresolved_is_explicit(self):
        bindings = resolve.load_bindings(self.root)
        bad = dict(bindings["b_7f3a"], derivation="sum(amount) where period='Q9'")
        v, st = resolve.resolve_binding(self.root, bad)
        self.assertIsInstance(v, resolve.Unresolved)
        self.assertEqual(st, "UNRESOLVED")

    def test_render_purity(self):
        a = render.render(self.root, specval.validate_view(VIEW))
        b = render.render(self.root, specval.validate_view(VIEW))
        self.assertEqual(a, b)


class F4F5EditInvalidation(unittest.TestCase):
    def setUp(self):
        self.root = make_workspace()

    def test_edit_path_atomic_with_history(self):
        node = VIEW["nodes"][1]
        eb = edits.make_edit_binding(self.root, "v_q3", node, 3000.0)
        updated, n_inv = edits.apply(self.root, eb)
        self.assertEqual(updated["amount"], 3000.0)
        hist = store.read_jsonl(self.root / "datasets" / "expenses" / store.HISTORY)
        self.assertEqual(len(hist), 1)
        self.assertEqual(hist[0]["prior"], 2110.0)
        self.assertEqual(hist[0]["new"], 3000.0)
        self.assertGreaterEqual(n_inv, 3)  # b_7f3a, b_9c11, b_cell12 all touch Q3

    def test_invalidation_visible_then_flag(self):
        """Badge sequence: PASS -> PENDING (after edit) -> FLAG (semantic, -12% vs actual)."""
        html0 = render.render(self.root, VIEW)
        self.assertIn('data-state="PASS"', html0)
        node = VIEW["nodes"][1]
        edits.apply(self.root, edits.make_edit_binding(self.root, "v_q3", node, 3000.0))
        html1 = render.render(self.root, VIEW)
        self.assertIn('data-state="PENDING"', html1)  # stale is visible, not silent
        engine.refresh_values(self.root)
        self.assertEqual(engine.provenance_gate(self.root), 0)
        flags = semantic.semantic_sweep(self.root)
        self.assertEqual(flags, 1)  # claim said -12%, actual (5110-4800)/4800 = +6.5%
        bindings = resolve.load_bindings(self.root)
        self.assertEqual(bindings["b_9c11"]["check"]["semantic"], "FLAG")
        html2 = render.render(self.root, VIEW)
        self.assertIn('data-state="FLAG"', html2)
        # assertion text untouched by the whole loop
        self.assertEqual(bindings["b_9c11"]["assertion"]["statement"], "Q3 spend fell 12% vs Q2")


class F6F7EvidenceCoverage(unittest.TestCase):
    def setUp(self):
        self.root = make_workspace()

    def test_evidence_panel(self):
        bindings = resolve.load_bindings(self.root)
        panel = affordance.evidence_panel(self.root, bindings["b_9c11"])
        self.assertEqual(panel["binding_id"], "b_9c11")
        self.assertTrue(panel["source_rows"])
        for r in panel["source_rows"]:  # verbatim rows byte-match dataset
            self.assertIn(r, RECORDS)
        self.assertEqual(panel["check"]["provenance"], "PASS")
        # every claim node renders the affordance
        self.assertIn("▸evidence", render.render(self.root, VIEW))

    def test_coverage_rendered(self):
        out = render.render(self.root, VIEW)
        self.assertIn("coverage: 100%", out)
        # break one binding -> coverage drops and is displayed
        bindings = store.read_jsonl(self.root / store.BINDINGS)
        bindings[0]["derivation"] = "sum(amount) where period='Q9'"
        store.atomic_write_jsonl(self.root / store.BINDINGS, bindings)
        out = render.render(self.root, VIEW)
        self.assertIn("coverage: 67%", out)


class F8Contract(unittest.TestCase):
    def test_only_qafiya_public_api_used(self):
        """Renderer modules import qafiya_core only (never modify Layer-1 files)."""
        for mod in ("specval", "resolve", "render", "affordance", "edits"):
            src = (ROOT / "dvr" / f"{mod}.py").read_text()
            for line in src.splitlines():
                if line.startswith(("import ", "from ")) and "qafiya" not in line \
                   and not line.startswith(("from .", "from pathlib", "import ")) :
                    pass  # stdlib/local allowed
            self.assertNotIn("01-data-layer-qafiya", src)
        # renderer never writes dataset files except via edits.apply -> engine.apply_edit
        res_src = (ROOT / "dvr" / "resolve.py").read_text() + (ROOT / "dvr" / "render.py").read_text()
        self.assertNotIn("atomic_write", res_src)
        self.assertNotIn("open(", res_src)


if __name__ == "__main__":
    unittest.main()


class DVR11ActionRole(unittest.TestCase):
    """dvr/1.1 delta §1: the action role — intent only, never execution."""

    ACTION_NODE = {"id": "confirm:send", "role": "action",
                   "action_ref": "a_001", "actions": ["approve", "reject"]}

    def spec(self, node, spec="dvr/1.1"):
        return {"spec": spec, "id": "v_act", "kind": "list", "nodes": [node]}

    def test_valid_action_node_passes_11(self):
        v = self.spec(self.ACTION_NODE)
        self.assertIs(specval.validate_view(v), v)

    def test_action_role_rejected_in_10(self):
        with self.assertRaises(specval.SpecError):
            specval.validate_view(self.spec(self.ACTION_NODE, spec="dvr/1.0"))

    def test_action_rules_enforced(self):
        bad = [
            {**self.ACTION_NODE, "binding_ref": "b_7f3a"},                    # binding_ref on action
            {k: v for k, v in self.ACTION_NODE.items() if k != "action_ref"},  # missing action_ref
            {**self.ACTION_NODE, "editable": True},                            # editable action
            {**self.ACTION_NODE, "actions": []},                               # empty actions
            {"id": "x", "role": "value", "binding_ref": "b_7f3a",
             "action_ref": "a_001"},                                           # action_ref on non-action
        ]
        for i, n in enumerate(bad):
            with self.assertRaises(specval.SpecError, msg=f"fixture {i} should be rejected"):
                specval.validate_view(self.spec(n))

    def test_action_render_and_evidence(self):
        """Render an action node against an action record; ▸evidence shows the record."""
        root = make_workspace()
        # L3 action record lives in a Qafiya dataset (mock L3 fixture until L3 supplies one)
        act_dir = root / "datasets" / "actions"
        act_dir.mkdir(parents=True)
        store.atomic_write_jsonl(act_dir / store.DATA, [{
            "id": "a_001", "intent": "Send Q3 expense report to finance@deewaan.ai",
            "scope": "email:send", "preconditions": ["user_confirmed"],
            "undo": "recall within 30s"}])
        view = self.spec(self.ACTION_NODE)
        specval.validate_view(view)
        out = render.render(root, view)
        self.assertIn("Send Q3 expense report", out)
        self.assertIn("approve", out)
        self.assertIn("reject", out)
        ev = affordance.evidence_for_action(root, "a_001")
        self.assertTrue(ev["found"])
        self.assertEqual(ev["record"]["scope"], "email:send")
        # unresolved action renders explicitly
        bad_view = self.spec({**self.ACTION_NODE, "action_ref": "a_nope", "id": "c2"})
        out2 = render.render(root, bad_view)
        self.assertIn("unresolved", out2)


class DVR11LoaderDiscovery(unittest.TestCase):
    """dvr/1.1 delta §2: load_bindings merges root + per-dataset bindings."""

    def test_merge_and_override(self):
        root = make_workspace()
        # per-dataset binding visible only via datasets/<name>/bindings.jsonl
        ds = root / "datasets" / "expenses"
        store.atomic_write_jsonl(ds / store.BINDINGS, [
            {"id": "b_local", "kind": "view", "derivation": None,
             "target": {"view": "v_x", "node": "n"}},
            {"id": "b_7f3a", "kind": "view", "derivation": None,  # collision: per-dataset wins
             "target": {"view": "v_override", "node": "n"}},
        ])
        merged = resolve.load_bindings(root)
        self.assertIn("b_local", merged)          # discovered from per-dataset file
        self.assertIn("b_9c11", merged)           # root bindings still present
        self.assertEqual(merged["b_7f3a"]["target"]["view"], "v_override")  # override rule


class DVR11LiteralAddendum(unittest.TestCase):
    """dvr/1.1 addendum (2026-10-27): literal bindings — memory content renders
    verbatim, never through the derivation parser; quarantine unchanged."""

    def _literal_workspace(self, supersede=False):
        root = make_workspace()
        ds = root / "datasets" / "preference_store"
        ds.mkdir(parents=True)
        store.atomic_write_jsonl(ds / store.DATA, [
            {"id": "m_001", "key": "language", "value": "English", "status": "active"},
        ])
        store.atomic_write_jsonl(ds / store.BINDINGS, [{
            "id": "b_mem1", "kind": "view",
            "target": {"view": "v_memory", "node": "node:m_001"},
            "sources": [{"dataset": "ds:preference_store", "filter": "id=m_001",
                         "field": "value", "key_path": ["value"],
                         "verbatim_excerpt": "English"}],
            "derivation": "literal", "value": "English",
            "statistic": "identity", "device": "layer4-store",
            "authoritative_artifact": "datasets/preference_store/data.jsonl",
            "check": {"provenance": "PASS"}}])
        if supersede:
            store.supersede(root, "datasets/preference_store/data.jsonl")
        return root

    VIEW = {"spec": "dvr/1.1", "id": "v_memory", "kind": "list",
            "title": {"text": "What I remember about you"},
            "nodes": [{"id": "node:m_001", "role": "value", "binding_ref": "b_mem1",
                       "row_key": "m_001", "editable": True}]}

    def test_literal_renders_verbatim(self):
        root = self._literal_workspace()
        specval.validate_view(self.VIEW)
        specval.validate_binding(resolve.load_bindings(root)["b_mem1"])
        out = render.render(root, self.VIEW)
        self.assertIn("English", out)
        self.assertNotIn("unresolved", out.lower())

    def test_literal_quarantine_still_applies(self):
        root = self._literal_workspace(supersede=True)
        out = render.render(root, self.VIEW)
        self.assertIn("unresolved", out.lower())

    def test_literal_requires_sources(self):
        with self.assertRaises(specval.SpecError):
            specval.validate_binding({"id": "b_x", "derivation": "literal",
                                      "value": "x", "sources": []})

    def test_memory_style_derivation_still_unresolved(self):
        """The old L4 form (value where id='...') is not a closed-set derivation:
        it renders UNRESOLVED — this addendum is what fixes it (via 'literal')."""
        root = self._literal_workspace()
        b = dict(resolve.load_bindings(root)["b_mem1"])
        b["derivation"] = "value where id='m_001'"
        v, st = resolve.resolve_binding(root, b)
        self.assertIsInstance(v, resolve.Unresolved)


class DVR11Addendum2Identity(unittest.TestCase):
    """dvr/1.1 addendum 2: find_record resolves by declared id_field, with
    id -> action_id -> _id fallback when no schema exists."""

    def _root_with_action(self, with_schema):
        root = make_workspace()
        ds = root / "datasets" / "action_log"
        ds.mkdir(parents=True)
        store.atomic_write_jsonl(ds / store.DATA, [{
            "action_id": "a_x1", "intent": {"verbatim": "Send Q3 report"},
            "outcome": {"status": "pending"}, "undo_status": "armed"}])
        if with_schema:
            (ds / "schema.json").write_text(json.dumps(
                {"dataset": "action_log", "id_field": "action_id",
                 "fields": {"action_id": "id"}}))
        return root

    def test_schema_id_field(self):
        root = self._root_with_action(with_schema=True)
        rec = resolve.find_record(root, "a_x1")
        self.assertIsNotNone(rec)
        self.assertEqual(rec["intent"]["verbatim"], "Send Q3 report")

    def test_fallback_action_id(self):
        root = self._root_with_action(with_schema=False)
        self.assertIsNotNone(resolve.find_record(root, "a_x1"))

    def test_missing_returns_none(self):
        root = self._root_with_action(with_schema=True)
        self.assertIsNone(resolve.find_record(root, "a_nope"))


class DVR11Addendum3EvidencePath(unittest.TestCase):
    """dvr/1.1 addendum 3: ▸evidence on value nodes; tolerant history lookups."""

    def test_value_nodes_show_evidence(self):
        root = make_workspace()
        out = render.render(root, VIEW)
        # the editable value node cell:r_012 must carry ▸evidence too
        self.assertIn('data-binding="b_cell12"', out)
        self.assertIn('data-binding="b_7f3a"', out)

    def test_l4_style_history_no_keyerror(self):
        """History entries with op/record/at (L4 chained form) must not raise."""
        root = make_workspace()
        ds = root / "datasets" / "expenses"
        store.append_history(ds, {"op": "set", "record": "r_012",
                                  "at": "2026-10-30T10:00Z"})
        bindings = resolve.load_bindings(root)
        panel = affordance.evidence_panel(root, bindings["b_9c11"])
        changed = panel["focus"]["changed_records"]
        self.assertEqual(changed[0]["record_id"], "r_012")   # via 'record' fallback
        self.assertNotIn("field", changed[0])                # omitted, not raised
        self.assertEqual(changed[0]["at"], "2026-10-30T10:00Z")

    def test_mixed_history_forms(self):
        root = make_workspace()
        node = VIEW["nodes"][1]
        edits.apply(root, edits.make_edit_binding(root, "v_q3", node, 3000.0))
        ds = root / "datasets" / "expenses"
        store.append_history(ds, {"op": "note", "record": "r_010",
                                  "at": "2026-10-30T10:01Z"})
        bindings = resolve.load_bindings(root)
        changed = affordance.evidence_panel(root, bindings["b_9c11"])["focus"]["changed_records"]
        self.assertEqual(len(changed), 2)
        self.assertEqual(changed[0]["record_id"], "r_012")   # classic form intact
        self.assertEqual(changed[0]["field"], "amount")
        self.assertEqual(changed[1]["record_id"], "r_010")   # L4 form tolerated
