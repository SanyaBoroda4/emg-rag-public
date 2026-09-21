"""Postgres connection helper. Reads credentials from .env via python-dotenv."""

import os

import psycopg
from dotenv import load_dotenv

load_dotenv()


def get_conn(**kwargs) -> psycopg.Connection:
    """Open a connection using PG_* variables from the environment / .env.

    Extra kwargs are passed through to psycopg.connect (e.g. autocommit=True,
    row_factory=...).
    """
    return psycopg.connect(
        host=os.environ.get("PG_HOST", "127.0.0.1"),
        port=int(os.environ.get("PG_PORT", "5433")),
        dbname=os.environ["PG_DB"],
        user=os.environ["PG_USER"],
        password=os.environ["PG_PASSWORD"],
        **kwargs,
    )


def get_serve_conn(**kwargs) -> psycopg.Connection:
    """Connect as rag_serve (WO16): INSERT/SELECT on serve.asks (UI history)
    plus SELECT on the v_* views. The HTTP API's own role; the pipeline it
    runs still uses get_conn / get_ro_conn exactly as the CLI does."""
    return psycopg.connect(
        host=os.environ.get("PG_HOST", "127.0.0.1"),
        port=int(os.environ.get("PG_PORT", "5433")),
        dbname=os.environ["PG_DB"],
        user="rag_serve",
        password=os.environ["PG_SERVE_PASSWORD"],
        **kwargs,
    )


def get_ro_conn(**kwargs) -> psycopg.Connection:
    """Connect as the rag_reader role: SELECT on the v_* views only, 10s
    statement_timeout. The text-to-SQL lane must use this and nothing else."""
    return psycopg.connect(
        host=os.environ.get("PG_HOST", "127.0.0.1"),
        port=int(os.environ.get("PG_PORT", "5433")),
        dbname=os.environ["PG_DB"],
        user="rag_reader",
        password=os.environ["PG_RO_PASSWORD"],
        options="-c statement_timeout=10s",
        **kwargs,
    )
