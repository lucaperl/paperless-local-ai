from __future__ import annotations

from history_runtime import HistoryIndex, _leaf_names_from_ids


TAX = {
    "tag_by_name": {"Inbox": 99, "LLM": 97, "LLM Error": 98, "Finance": 1, "Bank": 2, "Work": 3},
    "tag_by_id": {1: "Finance", 2: "Bank", 3: "Work", 97: "LLM", 98: "LLM Error", 99: "Inbox"},
    "parent_by_id": {1: None, 2: 1, 3: None, 99: None},
    "content_tag_ids": [1, 2, 3],
    "content_tags": ["Bank", "Finance", "Work"],
    "tags": [
        {"id": 2, "name": "Bank", "parent": 1},
        {"id": 1, "name": "Finance", "parent": None},
        {"id": 3, "name": "Work", "parent": None},
    ],
}


class Response:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


class FakeClient:
    def __init__(self, docs):
        self.docs = docs

    def request(self, method, path, params=None, **kwargs):
        assert method == "GET"
        assert path == "/api/documents/"
        params = params or {}
        raw_excluded = str(params.get("tags__id__none", ""))
        excluded = {int(x) for x in raw_excluded.split(",") if x}
        docs = [d for d in self.docs if not (excluded & set(d.get("tags", [])))]
        if params.get("ordering") == "-modified":
            docs = sorted(docs, key=lambda d: d.get("modified", ""), reverse=True)
            return Response({"count": len(docs), "results": docs[:1], "next": None})
        page = int(params.get("page", 1))
        size = int(params.get("page_size", 100))
        start = (page - 1) * size
        chunk = docs[start : start + size]
        return Response({"count": len(docs), "results": chunk, "next": "next" if start + size < len(docs) else None})


def doc(doc_id, text, tags, title=None):
    return {
        "id": doc_id,
        "title": title or f"Document {doc_id}",
        "content": text,
        "tags": tags,
        "modified": f"2026-08-{doc_id:02d}T12:00:00Z",
    }


def test_parent_is_pruned_when_child_is_present():
    assert _leaf_names_from_ids([1, 2], TAX) == ["Bank"]
    assert _leaf_names_from_ids([1], TAX) == ["Finance"]


def test_confident_repeated_history_routes_without_llm():
    docs = [
        doc(1, "salary statement employer august payroll gross net", [3]),
        doc(2, "salary statement employer july payroll gross net", [3]),
        doc(3, "bank account closure iban current account", [1, 2]),
    ]
    index = HistoryIndex()
    status = index.refresh(FakeClient(docs), TAX, "Inbox", force=True)
    assert status["status"] == "Ready"
    route = index.route("salary statement employer september payroll gross net")
    assert route["route"] == "history_match"
    assert route["tag"] == "Work"
    assert route["support"] >= 2


def test_ambiguous_history_falls_back_to_llm_with_positive_examples():
    docs = [
        doc(1, "contract account service confirmation alpha", [1]),
        doc(2, "contract account service confirmation beta", [3]),
        doc(3, "unrelated bank current account statement", [1, 2]),
    ]
    index = HistoryIndex()
    index.refresh(FakeClient(docs), TAX, "Inbox", force=True)
    route = index.route("contract account service confirmation gamma")
    assert route["route"] == "llm_fallback"
    assert all(example["tags"] for example in route["examples"])


def test_unreviewed_and_incomplete_documents_are_never_indexed():
    docs = [
        doc(1, "salary statement employer payroll gross net", [3]),
        doc(2, "salary statement employer payroll gross net", [3, 99]),
        doc(3, "salary statement employer payroll gross net", [3, 97]),
        doc(4, "salary statement employer payroll gross net", [3, 98]),
    ]
    index = HistoryIndex()
    status = index.refresh(
        FakeClient(docs),
        TAX,
        ["Inbox", "LLM", "LLM Error"],
        force=True,
    )
    assert status["reviewed_documents"] == 1


def test_conflicting_similar_documents_are_only_flagged_for_review():
    docs = [
        doc(1, "social insurance notification employer payroll employee", [3]),
        doc(2, "social insurance notification employer payroll employee year", [3]),
        doc(3, "social insurance notification employer payroll employee correction", [1]),
        doc(4, "social insurance notification employer payroll employee cancellation", [1]),
    ]
    index = HistoryIndex()
    status = index.refresh(FakeClient(docs), TAX, "Inbox", force=True)
    assert status["potential_inconsistency_count"] >= 1
    combos = status["potential_inconsistencies"][0]["tag_sets"]
    assert {tuple(item["tags"]) for item in combos} >= {("Work",), ("Finance",)}


def test_inconsistency_families_use_complete_linkage_not_chain_linkage():
    # A~B and B~C are both above the 0.50 threshold, but A~C is not.
    # Complete-linkage therefore must not merge all three into one family.
    docs = [
        doc(1, "aaaa bbbb cccc dddd", [3]),
        doc(2, "aaaa bbbb cccc eeee", [3]),
        doc(3, "aaaa bbbb eeee ffff", [1]),
    ]
    index = HistoryIndex()
    status = index.refresh(FakeClient(docs), TAX, "Inbox", force=True)
    assert status["potential_inconsistency_count"] == 0
