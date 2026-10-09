"""``concho-api``: serve a team repo's results locally (P5.4) and ingest them (P5.3).

    concho-api ingest [--repo DIR] [--db FILE] [--snapshot ID] [--force]
    concho-api summary [--repo DIR] [--db FILE] [--snapshot ID]
    concho-api serve [--repo DIR] [--db FILE] [--host 127.0.0.1] [--port 8000] [--enable-sql]

Local only: no hosting, no deployment (decision D2 is open). The bearer token is read from
``$CONCHO_API_TOKEN``; there is deliberately no ``--token`` option (shell history).
``serve`` ingests snapshots that are not in the database yet, unless ``--no-ingest``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import schema
from .ingest import IngestError, default_db_path, ingest_repo


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="concho-api", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--repo", default=".", metavar="DIR",
                       help="team repo with results/ (default: current directory)")
        p.add_argument("--db", metavar="FILE",
                       help="database file (default: <repo>/.concho/concho.db)")

    p = sub.add_parser("ingest", help="load results/ into the SQLite database")
    common(p)
    p.add_argument("--snapshot", metavar="ID", help="only this snapshot (default: all new ones)")
    p.add_argument("--force", action="store_true", help="re-ingest snapshots already in the db")

    p = sub.add_parser("summary", help="print the precomputed summary JSON of a snapshot")
    common(p)
    p.add_argument("--snapshot", metavar="ID", help="default: the latest")

    p = sub.add_parser("serve", help="serve the data API on localhost")
    common(p)
    p.add_argument("--host", default="127.0.0.1", help="default 127.0.0.1 (local only)")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--enable-sql", action="store_true",
                   help="enable POST /sql (read-only SELECT, row cap)")
    p.add_argument("--no-ingest", action="store_true",
                   help="serve the database as it is")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo = Path(args.repo).resolve()
    db = Path(args.db) if args.db else default_db_path(repo)
    try:
        if args.command == "ingest":
            print(json.dumps(ingest_repo(repo, db, snapshot=args.snapshot, force=args.force),
                             indent=2))
            return 0
        if args.command == "summary":
            from .queries import resolve_snapshot
            conn = schema.connect(str(db), readonly=True)
            try:
                print(resolve_snapshot(conn, args.snapshot)["summary_json"])
            finally:
                conn.close()
            return 0
        return _serve(args, repo, db)
    except (IngestError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _serve(args: argparse.Namespace, repo: Path, db: Path) -> int:
    if not os.environ.get("CONCHO_API_TOKEN"):
        print("error: set CONCHO_API_TOKEN (the API does not run without a bearer token)",
              file=sys.stderr)
        return 1
    try:
        import uvicorn

        from .app import create_app
    except ImportError:
        print('error: the API needs FastAPI: pip install "concho[api]"', file=sys.stderr)
        return 1
    if not args.no_ingest:
        result = ingest_repo(repo, db)
        print(f"ingested {len(result['ingested'])} new snapshot(s); "
              f"{len(result['existing'])} already in {db}", file=sys.stderr)
    app = create_app(db, enable_sql=args.enable_sql or None)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
