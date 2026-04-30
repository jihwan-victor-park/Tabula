"""
MongoDB client singleton for Clawbot.

Reads connection details from environment variables:
  MONGODB_URI  — connection string (default: mongodb://localhost:27017)
  MONGODB_DB   — database name    (default: clawbot)

Usage:
    from clawbot.tools.mongodb import get_col
    items = get_col("inventory")
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

load_dotenv()

if TYPE_CHECKING:
    pass

_client: MongoClient | None = None


def get_client() -> MongoClient:
    global _client
    if _client is None:
        uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
        _client = MongoClient(uri)
    return _client


def get_db() -> Database:
    db_name = os.getenv("MONGODB_DB", "clawbot")
    return get_client()[db_name]


def get_col(name: str) -> Collection:
    """Return a named collection from the clawbot database."""
    return get_db()[name]
