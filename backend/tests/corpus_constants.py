"""Corpus constants for Chester baseline — refresh via export_test_corpus.py."""

WORKSPACE_ID = "eca7aebb-0b4d-433d-8e73-9144c04eb0d7"
DOCUMENT_ID = "b65e3196-7199-446e-a910-6476d23b7bc8"
DOCUMENT_NAME = "Chester v Municipality of Waverly .pdf"

# Primary eval benchmark (page 3) — damages claim line
BENCHMARK_LINE = "The plaintiff claimed damages in the sum of £1,000."
BENCHMARK_PAGE = 3
BENCHMARK_CHUNK_ID = "d4ae199c-81ce-4dd8-82ab-3932898a5576"
BENCHMARK_AMOUNT_CANONICAL = "1000_gbp"
BENCHMARK_PARTY_CANONICAL = "the plaintiff"

SIMPLE_QUERIES = {
    "liability": {"min_hits": 1},
    "negligence": {"min_hits": 1},
    "Hambrook": {"min_hits": 1},
    "plaintiff claimed damages": {"min_hits": 1, "gold_chunk_id": BENCHMARK_CHUNK_ID},
}

BENCHMARK_QUERIES = {
    "exact": "plaintiff claimed damages in the sum of £1,000",
    "complex": "What damages sum did the plaintiff claim?",
    "paraphrase": "plaintiff damages sum claimed",
    "carp": "case context for supreme court with plaintiff damages of £1,000",
}

# Page 3 has party + identifier + amount co-occurrence in Chester corpus
CARP_INTERSECTION_PAGE = 3

PARTY_ON_PAGE_3 = {"supreme court", "stokes brothers", "high court", "refused", "the full court", "full court", "the plaintiff"}
IDENTIFIER_ON_PAGE_3 = {"refused", "high court"}
AMOUNT_ON_PAGE_3 = {"1000_gbp"}
