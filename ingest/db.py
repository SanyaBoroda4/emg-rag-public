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
