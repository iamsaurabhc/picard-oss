from app.services.case_scoping import resolve_case_document_ids


def test_resolve_case_documents_narrows_to_matching_doc(db_session, corpus_session):
    from tests.corpus_constants import DOCUMENT_ID, WORKSPACE_ID

    resolved = resolve_case_document_ids(
        corpus_session,
        WORKSPACE_ID,
        ["chester", "waverley"],
        document_ids=None,
    )
    assert resolved == [DOCUMENT_ID]
