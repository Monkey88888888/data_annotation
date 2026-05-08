"""Apply SQL schema files to a Supabase Postgres instance.

Usage::

    python -m data_annotation.db.apply_schema           # applies both default files
    python -m data_annotation.db.apply_schema schema.sql
    python -m data_annotation.db.apply_schema --dry-run

Reads SUPABASE_DB_URL from the environment (or .env). Supabase shows the
password wrapped in [brackets]; we strip them and URL-encode special
characters before connecting.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import quote

import psycopg
from dotenv import load_dotenv


DEFAULT_SCHEMAS = ("schema.sql", "annotations_schema.sql")


def _normalize_db_url(raw: str) -> str:
    """Supabase prints connection strings with the password in [brackets].
    Strip them and URL-encode the password so special characters survive."""
    if "://" not in raw:
        raise ValueError("SUPABASE_DB_URL must look like postgresql://...")

    scheme, rest = raw.split("://", 1)
    if "@" not in rest:
        return raw

    # Split on the LAST '@' so an '@' inside the password doesn't confuse us.
    userinfo, host_part = rest.rsplit("@", 1)
    if ":" not in userinfo:
        return raw

    user, password = userinfo.split(":", 1)
    password = password.strip()
    if password.startswith("[") and password.endswith("]"):
        password = password[1:-1]
    encoded = quote(password, safe="")
    return f"{scheme}://{user}:{encoded}@{host_part}"


def _resolve_schema_paths(names: list[str]) -> list[Path]:
    here = Path(__file__).resolve().parent
    paths: list[Path] = []
    for name in names:
        path = Path(name)
        if not path.is_absolute():
            path = here / name
        if not path.exists():
            raise FileNotFoundError(path)
        paths.append(path)
    return paths


def apply_schema(db_url: str, schema_paths: list[Path], dry_run: bool = False) -> None:
    sql_blobs = [(path, path.read_text(encoding="utf-8")) for path in schema_paths]
    if dry_run:
        for path, sql in sql_blobs:
            print(f"--- {path}")
            print(sql)
        return

    with psycopg.connect(db_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            for path, sql in sql_blobs:
                print(f"applying {path.name}...")
                cur.execute(sql)
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name IN ('documents_raw', 'annotations')
                ORDER BY table_name
                """
            )
            rows = cur.fetchall()
            print("public tables present:", [row[0] for row in rows])


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("schemas", nargs="*", default=list(DEFAULT_SCHEMAS))
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = parse_args(argv or sys.argv[1:])
    db_url_raw = os.environ.get("SUPABASE_DB_URL")
    if not db_url_raw and not args.dry_run:
        print("SUPABASE_DB_URL not set", file=sys.stderr)
        return 2
    db_url = _normalize_db_url(db_url_raw) if db_url_raw else ""
    apply_schema(db_url, _resolve_schema_paths(args.schemas), dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
