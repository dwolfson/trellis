#!/usr/bin/env python3
"""Measure what chunk size each path boundary of a resource actually wants.

Reads containment trees already in Postgres — no re-parse, no fetch — and
reports per top-level path boundary. Reports only: changing a chunk size means
re-embedding a corpus, so the decision stays with a person.

Requires ARTIFACT_TREE_ENABLED to have been on for an ingest of the resource,
since it measures the trees that ingest produced.

Usage:
    python scripts/profile_corpus.py egeria_docs
    python scripts/profile_corpus.py egeria_python_git --min-docs 20
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("slug")
    ap.add_argument("--min-docs", type=int, default=5,
                    help="skip boundaries with fewer documents than this — a "
                         "percentile over three files is noise, not a measurement")
    args = ap.parse_args()

    import psycopg2
    import psycopg2.extras
    from trellis_artifact_tree.model import ArtifactTree, Node, Provenance, Rung
    from trellis_artifact_tree.profile import compare_to, profile_trees

    from resource_explorer.config import get_config
    from resource_explorer.configdata.collection_config import COLLECTION_TYPES

    pg = get_config().pgvector
    conn = psycopg2.connect(
        host=pg.host, port=pg.port, dbname=pg.dbname,
        user=pg.db_user, password=pg.password,
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
    cur = conn.cursor()
    cur.execute(
        """SELECT a.artifact_id, a.source_id, a.extraction_fidelity,
                  nd.node_id, nd.parent_id, nd.kind, r.text
             FROM artifact_tree.artifact a
             JOIN artifact_tree.artifact_node nd USING (artifact_id)
             LEFT JOIN artifact_tree.artifact_node_rung r
                    ON r.node_id = nd.node_id AND r.rung = 0
            WHERE a.artifact_id LIKE %s""",
        (f"{args.slug}:%",),
    )
    rows = cur.fetchall()
    conn.close()
    if not rows:
        print(f"No trees for {args.slug!r}. Re-ingest with ARTIFACT_TREE_ENABLED=true.",
              file=sys.stderr)
        return 1

    by_artifact: dict[str, list[dict]] = defaultdict(list)
    source_of: dict[str, str] = {}
    for row in rows:
        by_artifact[row["artifact_id"]].append(row)
        source_of[row["artifact_id"]] = row["source_id"]

    by_boundary: dict[str, list] = defaultdict(list)
    for artifact_id, node_rows in by_artifact.items():
        source = source_of[artifact_id]
        boundary = source.split("/", 1)[0] if "/" in source else "(root)"
        prov = Provenance(source_kind="repo", source_id=source, fetched_at="")
        nodes = tuple(
            Node(node_id=r["node_id"], artifact_id=artifact_id, kind=r["kind"],
                 parent_id=r["parent_id"],
                 rungs={Rung.FULL: r["text"]} if r["text"] else {})
            for r in node_rows
        )
        try:
            by_boundary[boundary].append(ArtifactTree(artifact_id, prov, nodes))
        except Exception:
            # A tree that will not reconstruct is skipped, not fatal: one bad
            # artifact must not cost the measurement of a whole corpus.
            continue

    configured = {
        "markdown_docs": COLLECTION_TYPES["markdown_docs"].chunk_size,
        "python_code": COLLECTION_TYPES["python_code"].chunk_size,
    }
    print(f"{args.slug} — configured markdown_docs={configured['markdown_docs']}, "
          f"python_code={configured['python_code']}\n")
    print(f"{'boundary':26}{'docs':>6}{'u/doc':>7}{'p75 unit':>10}{'p75 doc':>9}"
          f"{'chunk':>7}  basis")
    for boundary, trees in sorted(by_boundary.items(), key=lambda kv: -len(kv[1])):
        if len(trees) < args.min_docs:
            continue
        p = profile_trees(boundary, trees)
        if not p.documents:
            continue
        print(f"{boundary[:24]:26}{p.documents:>6}{p.median_units_per_doc:>7.1f}"
              f"{p.p75_unit_tokens:>10}{p.p75_doc_tokens:>9}{p.chunk_size:>7}  {p.basis}")
    print()
    print("Reports only. Changing a chunk size means re-embedding the corpus.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
