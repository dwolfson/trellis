"""pyegeria 6.2.8 made db_user/db_pwd on create_postgres_{server,database}_element_from_template deprecated and
IGNORED (DeprecationWarning; credentials now come from secretsStorePathName/secretsCollectionName).

RE must not silently lose the credential the JDBC cataloguer uses. It does not call those builders: the surveyor
hand-builds the placeholder body and sends it through create_elem_from_template. This pins that, so a future switch
to the builders (which would drop databaseUserId/databasePassword) fails here and becomes an owner decision."""
from __future__ import annotations

import ast
import inspect
import warnings
from pathlib import Path

import resource_explorer

BUILDERS = {"create_postgres_server_element_from_template", "create_postgres_database_element_from_template",
            "_async_create_postgres_server_element_from_template", "_async_create_postgres_database_element_from_template"}


def test_no_re_source_calls_the_deprecated_postgres_builders():
    root = Path(resource_explorer.__file__).parent
    hits = []
    for py in root.rglob("*.py"):
        for node in ast.walk(ast.parse(py.read_text())):
            if isinstance(node, ast.Attribute) and node.attr in BUILDERS:
                hits.append(f"{py.relative_to(root)}:{node.lineno}")
    assert not hits, f"RE now calls a builder whose db_user/db_pwd 6.2.8 ignores: {hits}"


def test_surveyor_still_sends_credential_placeholders_through_raw_template_path():
    from resource_explorer.surveyors.database import egeria_database_surveyor as m
    src = inspect.getsource(m)
    assert '"databaseUserId": db_user' in src and '"databasePassword": db_pwd' in src
    assert "_create_postgres_element_from_template(" in src


def test_pyegeria_628_builders_warn_and_drop_credentials():
    from pyegeria.omvs.automated_curation import AutomatedCuration
    sig = inspect.signature(AutomatedCuration._async_create_postgres_server_element_from_template)
    assert {"secrets_store_path_name", "secrets_collection_name"} <= set(sig.parameters)
    assert sig.parameters["db_pwd"].default is None  # optional, ignored
    assert "DeprecationWarning" in inspect.getsource(AutomatedCuration._async_create_postgres_server_element_from_template)
