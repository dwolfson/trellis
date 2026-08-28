"""Connection configuration for ArtifactTreeStore.

A plain frozen stdlib dataclass, not pydantic/BaseSettings, and it never reads
the environment or a YAML file. Resource Explorer and Egeria Advisor each
already own their config resolution and each builds this as the last step
before constructing a store. Making this type read the environment would add a
third config surface racing the two that exist -- the same reasoning as
trellis_vectorstore.config.PgVectorStoreConfig, and the same conclusion.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ArtifactTreeConfig:
    host: str
    port: int
    dbname: str
    user: str
    password: str
    # None => unqualified table names, relying on the Postgres search_path.
    # A value => every identifier is schema-qualified. The tree is deliberately
    # NOT in either app's own schema (RE's "resource_explorer", EA's tables):
    # both apps write it, so it belongs to neither. Give it its own schema.
    schema: str | None = "artifact_tree"
    max_connections: int = 10
