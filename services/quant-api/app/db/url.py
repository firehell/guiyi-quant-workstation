from __future__ import annotations


def normalize_database_url(url: str) -> str:
    """Ensure SQLAlchemy uses psycopg v3 instead of defaulting to psycopg2."""
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    return url
