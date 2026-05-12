"""Redis-backed user storage with full CRUD support.

Each user is stored as a Redis hash at ``USERS_CONFIG:<keyword>``.
A companion set ``USERS_CONFIG:keywords`` tracks all known keywords
so we can enumerate users without SCAN.
"""

import json
import logging
import os
from typing import Any, Sequence

import redis
from redis import Redis

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
USER_KEY_PREFIX = "USERS_CONFIG"
KEYWORDS_KEY    = f"{USER_KEY_PREFIX}:keywords"

# Every field a user dict can contain (matches users.json schema).
ALL_FIELDS = [
    "name", "email", "keyword",
    "active", "use_email", "use_whatsapp",
    "max_email_results", "days_threshold",
    "schedule_time",
    "smtp_host_user", "smtp_host_password",
    "mobile",
]

# Fields that need type coercion when reading back from Redis (Redis stores
# everything as strings).
BOOL_FIELDS = {"active", "use_email", "use_whatsapp"}
INT_FIELDS  = {"max_email_results", "days_threshold"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_user_key(keyword: str) -> str:
    return f"{USER_KEY_PREFIX}:{keyword}"


def _serialize(value: Any) -> str:
    """Convert a Python value to its Redis-safe string representation."""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    return str(value) if value else ""


def _deserialize(field: str, raw: str | None) -> Any:
    """Convert a raw Redis string back to the correct Python type."""
    if raw is None:
        return None
    if field in BOOL_FIELDS:
        return raw == "1"
    if field in INT_FIELDS:
        try:
            return int(raw)
        except (ValueError, TypeError):
            return 0
    return raw


def _coerce_user_dict(raw: dict[str, Any]) -> dict[str, Any]:
    """Ensure all values in a user dict are the right Python types."""
    cooked: dict[str, Any] = {}
    for field, val in raw.items():
        if field in BOOL_FIELDS:
            if isinstance(val, bool):
                cooked[field] = val
            elif isinstance(val, str):
                cooked[field] = val.strip().lower() in ("1", "true", "yes", "y")
            else:
                cooked[field] = bool(val)
        elif field in INT_FIELDS:
            try:
                cooked[field] = int(val)
            except (ValueError, TypeError):
                cooked[field] = 0
        else:
            cooked[field] = str(val).strip() if val else ""
    return cooked


# ---------------------------------------------------------------------------
# RedisUserManager
# ---------------------------------------------------------------------------
class RedisUserManager:
    """Manage users stored as Redis hashes.

    Uses ``HSET``/``HGETALL`` for single-user ops and pipeline batching for
    bulk reads.  A companion ``SET`` (``USERS_CONFIG:keywords``) tracks all
    known keywords.

    Typical usage::

        mgr = RedisUserManager()
        mgr.add_or_update({"keyword": "bob", "name": "Bob", ...})
        users = mgr.get_all()
        mgr.delete("bob")
    """

    def __init__(self, r: Redis | None = None):
        if r is None:
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            r = redis.from_url(redis_url, decode_responses=True)
        self.r: Redis = r

    # ------------------------------------------------------------------
    # Single-user CRUD
    # ------------------------------------------------------------------
    def add_or_update(self, user: dict[str, Any]) -> None:
        """Insert or fully replace a user hash.  ``user`` must include
        a ``keyword`` field."""
        keyword = user.get("keyword", "")
        if not keyword:
            raise ValueError("User dict must contain a non-empty 'keyword' field")

        key = _make_user_key(keyword)
        cooked = _coerce_user_dict(user)

        mapping: dict[str, str] = {}
        for field in ALL_FIELDS:
            val = cooked.get(field)
            mapping[field] = _serialize(val) if val is not None else ""

        pipe = self.r.pipeline()
        pipe.hset(key, mapping=mapping)
        pipe.sadd(KEYWORDS_KEY, keyword)
        pipe.execute()
        _logger.debug("Saved user %s (%s)", keyword, cooked.get("name", "?"))

    def get(self, keyword: str) -> dict[str, Any] | None:
        """Return a single user dict, or ``None`` if not found."""
        key = _make_user_key(keyword)
        if not self.r.exists(key):
            return None
        raw = self.r.hgetall(key)
        return self._raw_to_dict(raw, keyword)

    def delete(self, keyword: str) -> bool:
        """Remove a user hash and its keyword from the index set.
        Returns ``True`` if the user existed."""
        key = _make_user_key(keyword)
        existed = bool(self.r.exists(key))
        pipe = self.r.pipeline()
        pipe.delete(key)
        pipe.srem(KEYWORDS_KEY, keyword)
        pipe.execute()
        if existed:
            _logger.debug("Deleted user %s", keyword)
        return existed

    def exists(self, keyword: str) -> bool:
        return bool(self.r.exists(_make_user_key(keyword)))

    def count(self) -> int:
        return self.r.scard(KEYWORDS_KEY)

    # ------------------------------------------------------------------
    # Bulk reads
    # ------------------------------------------------------------------
    def get_all(self) -> list[dict[str, Any]]:
        """Return all users as a list of dicts (bulk-pipelined)."""
        keywords = self._all_keywords()
        if not keywords:
            return []

        pipe = self.r.pipeline(transaction=False)
        for kw in keywords:
            pipe.hgetall(_make_user_key(kw))
        results: list[dict[bytes | str, str]] = pipe.execute()  # type: ignore[assignment]

        users: list[dict[str, Any]] = []
        for kw, raw in zip(keywords, results):
            users.append(self._raw_to_dict(raw, kw))
        return users

    def _all_keywords(self) -> list[str]:
        """Return every keyword tracked in the index set, sorted."""
        return sorted(self.r.smembers(KEYWORDS_KEY))

    def import_from_json(self, path: str = "users.json") -> int:
        """Bulk-import users from a JSON file (same format as users.json).
        Returns the number of users imported."""
        if not os.path.isfile(path):
            _logger.warning("Import failed: file not found (%s)", path)
            return 0

        with open(path, "r", encoding="utf-8") as f:
            source = json.load(f)

        if not isinstance(source, list):
            _logger.warning("Import failed: %s does not contain a JSON array", path)
            return 0

        pipe = self.r.pipeline()
        for user in source:
            keyword = user.get("keyword", "")
            if not keyword:
                continue
            cooked = _coerce_user_dict(user)
            mapping = {f: _serialize(cooked.get(f)) for f in ALL_FIELDS}
            pipe.hset(_make_user_key(keyword), mapping=mapping)
            pipe.sadd(KEYWORDS_KEY, keyword)
        results = pipe.execute()

        imported = sum(1 for r in results[::2] if r)  # every 2nd = HSET return
        _logger.info("Imported %d user(s) from %s", imported, path)
        return imported

    def export_to_json(self, path: str = "users.json") -> int:
        """Bulk-export all Redis users to a JSON file.  Returns count."""
        users = self.get_all()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(users, f, indent=2, ensure_ascii=False)
        _logger.info("Exported %d user(s) to %s", len(users), path)
        return len(users)

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------
    def activate(self, keyword: str) -> bool:
        return self._toggle_bool_field(keyword, "active", True)

    def deactivate(self, keyword: str) -> bool:
        return self._toggle_bool_field(keyword, "active", False)

    def _toggle_bool_field(self, keyword: str, field: str, value: bool) -> bool:
        key = _make_user_key(keyword)
        if not self.r.exists(key):
            return False
        self.r.hset(key, field, "1" if value else "0")
        return True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _raw_to_dict(self, raw: dict[str, str] | dict[bytes, bytes],
                     keyword: str | None = None) -> dict[str, Any]:
        """Convert a Redis HGETALL result into a typed user dict."""
        user: dict[str, Any] = {}
        for f, v in raw.items():
            field = f.decode() if isinstance(f, bytes) else f
            value = v.decode() if isinstance(v, bytes) else v
            user[field] = _deserialize(field, value)
        # Ensure keyword is present (it's in the key, not always the hash)
        if keyword and "keyword" not in user:
            user["keyword"] = keyword
        return user

    def clear_all(self) -> int:
        """Delete ALL user hashes and the keyword set.  Returns count."""
        keywords = self._all_keywords()
        if not keywords:
            return 0
        pipe = self.r.pipeline()
        pipe.delete(*[_make_user_key(kw) for kw in keywords])
        pipe.delete(KEYWORDS_KEY)
        pipe.execute()
        _logger.info("Cleared %d user(s)", len(keywords))
        return len(keywords)
