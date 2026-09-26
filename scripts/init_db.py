"""Create the database named in AUDIO_SEARCH_DATABASE_URL if missing, then apply db/schema.sql.

Idempotent by default. Run from the repo root inside the venv:  python scripts/init_db.py
`--recreate` DROPS the chunk and audio_file tables first (all ingested data is lost; re-run
scripts/ingest.py). It is needed when the schema changes, e.g. the embedding dimension.
"""
import sys
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from api.settings import load_settings  # noqa: E402


def main(argv: list[str]) -> int:
    recreate = "--recreate" in argv
    url = load_settings().database_url
    dbname = conninfo_to_dict(url)["dbname"]
    with psycopg.connect(make_conninfo(url, dbname="postgres"), autocommit=True) as admin:
        if admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,)).fetchone():
            print(f"database {dbname!r} exists")
        else:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))
            print(f"database {dbname!r} created")
    with psycopg.connect(url) as conn:
        if recreate:
            counts = [conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] if conn.execute(
                "SELECT to_regclass(%s)", (t,)).fetchone()[0] else 0 for t in ("audio_file", "chunk")]
            conn.execute("DROP TABLE IF EXISTS chunk, audio_file CASCADE")
            print(f"dropped tables audio_file ({counts[0]} rows) and chunk ({counts[1]} rows)")
        conn.execute((ROOT / "db" / "schema.sql").read_text())
        version = conn.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'").fetchone()[0]
    print(f"schema applied; pgvector {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
