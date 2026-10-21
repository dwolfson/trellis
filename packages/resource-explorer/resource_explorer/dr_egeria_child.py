"""The `dr_egeria` child for a SIGNED-IN person: `python -m resource_explorer.dr_egeria_child ... <doc.md>`.

pyegeria's `dr_egeria` CLI needs a password and RE holds none for a signed-in person (only their Egeria bearer
token). This process does what the CLI does (`--process --summary-only`) with a client the RE factory builds from
that token, so the document is applied as that person. The token arrives in `RE_DR_EGERIA_CHILD_TOKEN` (this
child's environment only, never argv), and the user, server and url are explicit arguments: there is no default
identity here, a missing one exits 2.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

TOKEN_ENV = "RE_DR_EGERIA_CHILD_TOKEN"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dr_egeria_child")
    ap.add_argument("--userid", required=True)
    ap.add_argument("--server", required=True)
    ap.add_argument("--url", required=True)
    ap.add_argument("input_file")
    args = ap.parse_args(argv)
    token = os.environ.get(TOKEN_ENV, "")
    if not args.userid.strip() or not token:
        print("no Egeria identity set; pass --as or sign in", file=sys.stderr)
        return 2

    from md_processing.dr_egeria import process_md_file_v2
    from pyegeria import EgeriaTech

    from resource_explorer.egeria_clients import KIND_CALLER, egeria_client
    from resource_explorer.egeria_identity import EgeriaIdentity

    identity = EgeriaIdentity(user_id=args.userid, token=token, kind=KIND_CALLER)
    clients = egeria_client(identity, purpose="Dr.Egeria document run (signed-in person)", view_server=args.server,
                            platform_url=args.url, shared=False)
    client = clients.of(EgeriaTech)
    asyncio.run(process_md_file_v2(input_file=args.input_file, output_folder="", directive="process",
                                   client=client, parse_summary="none", attribute_logs="info",
                                   usage_level="Basic", summary_only=True, debug=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
