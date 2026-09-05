"""EA's PgVectorStore keeps accepting description= from the ingestion callers (trevor, 2026-09-04)."""
from unittest.mock import patch

from advisor.vector_store_pg import PgVectorStore


def test_create_collection_accepts_description_and_forwards_the_rest():
    with patch("trellis_vectorstore.pg.PgVectorStore.create_collection", return_value="pyegeria_dre") as base:
        store = PgVectorStore.__new__(PgVectorStore)  # no connection needed for the signature check
        out = PgVectorStore.create_collection(store, "pyegeria_drE", drop_if_exists=False, description="Dr.Egeria docs")
    assert out == "pyegeria_dre"
    base.assert_called_once_with("pyegeria_drE", drop_if_exists=False)
