"""Filesystem storage for briefs: atomic writes, per-slug locks, trash.

One brief is one directory: data/briefs/<slug>/brief.json. Every write goes
through a temp file plus os.replace, and the previous file is rotated to
brief.json.bak so a torn write is always recoverable.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .schema import (
    DEFAULT_PERIOD_DAYS,
    SLUG_RE,
    VALID_LANG,
    VOLATILE_FIELDS,
    BriefNotFound,
    StorageError,
    check_schema,
    new_brief,
    normalise_lang,
    normalise_period_days,
    require_text,
    slugify,
    summarise,
    utcnow,
    validate_slug,
)
from .schema import MAX_QUERY

_locks: Dict[str, "threading.RLock"] = {}
_locks_guard = threading.Lock()


def _lock_for(key: str):
    """Reentrant: a mutation already holding the lock may trigger a recovery write."""
    with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.RLock()
            _locks[key] = lock
        return lock


class Storage:
    """All brief persistence. One instance per app; data_dir is the root."""

    def __init__(self, data_dir: os.PathLike[str] | str) -> None:
        self.root = Path(data_dir).resolve()
        self.briefs_dir = self.root / "briefs"
        self.trash_dir = self.root / ".trash"
        self.briefs_dir.mkdir(parents=True, exist_ok=True)
        self.trash_dir.mkdir(parents=True, exist_ok=True)

    # -- paths -----------------------------------------------------------
    def brief_dir(self, slug: str) -> Path:
        validate_slug(slug)
        path = (self.briefs_dir / slug).resolve()
        if path != self.briefs_dir / slug or self.briefs_dir not in path.parents:
            raise ValueError("invalid slug")
        return path

    def brief_file(self, slug: str) -> Path:
        return self.brief_dir(slug) / "brief.json"

    def _lock(self, slug: str):
        return _lock_for(f"{self.root}::{slug}")

    # -- read ------------------------------------------------------------
    def exists(self, slug: str) -> bool:
        return self.brief_file(slug).is_file()

    def load_brief(self, slug: str) -> Dict[str, Any]:
        path = self.brief_file(slug)
        backup = path.with_suffix(".json.bak")
        try:
            return check_schema(json.loads(path.read_text(encoding="utf-8")))
        except FileNotFoundError:
            data = self._load_backup(backup)
            if data is None:
                raise BriefNotFound(slug)
            return check_schema(data)
        except (json.JSONDecodeError, UnicodeDecodeError):
            data = self._load_backup(backup)
            if data is not None:
                return check_schema(data)
            return self._restart_empty(slug, path)

    @staticmethod
    def _load_backup(backup: Path) -> Optional[Dict[str, Any]]:
        try:
            data = json.loads(backup.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        data["recovered"] = True
        return data

    def _restart_empty(self, slug: str, path: Path) -> Dict[str, Any]:
        """Both copies are unreadable: keep the damaged bytes, restart empty.

        Losing a brief is acceptable — losing it silently is not, so the
        corrupt file is preserved and the caller gets a data_loss flag.
        """
        keep = path.with_name(f"brief.json.corrupt-{int(time.time())}")
        while keep.exists():
            keep = keep.with_name(f"{keep.name}x")
        os.replace(path, keep)
        brief = new_brief(slug, slug, DEFAULT_PERIOD_DAYS, list(VALID_LANG))
        with self._lock(slug):
            self._write_brief(slug, brief)
        brief["data_loss"] = True
        return brief

    def list_briefs(self) -> List[Dict[str, Any]]:
        summaries: List[Dict[str, Any]] = []
        for entry in sorted(self.briefs_dir.iterdir()):
            if not entry.is_dir() or not SLUG_RE.match(entry.name):
                continue
            try:
                brief = self.load_brief(entry.name)
            except StorageError:
                continue
            summaries.append(summarise(brief))
        summaries.sort(key=lambda item: item.get("created") or "", reverse=True)
        return summaries

    # -- write -----------------------------------------------------------
    def _write_brief(self, slug: str, brief: Dict[str, Any]) -> None:
        path = self.brief_file(slug)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        payload = {k: v for k, v in brief.items() if k not in VOLATILE_FIELDS}
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if path.is_file():
            os.replace(path, path.with_suffix(".json.bak"))
        os.replace(tmp, path)

    def new_slug(self, query: str) -> str:
        base = slugify(query)
        if not self.exists(base):
            return base
        for index in range(2, 1000):
            suffix = f"-{index}"
            candidate = f"{base[: 64 - len(suffix)]}{suffix}"
            if not self.exists(candidate):
                return candidate
        raise StorageError("could not allocate slug")

    def create_brief(
        self,
        query: str,
        period_days: Any = DEFAULT_PERIOD_DAYS,
        lang: Any = None,
    ) -> Dict[str, Any]:
        query = require_text(query, "query", MAX_QUERY)
        days = normalise_period_days(period_days)
        codes = normalise_lang(lang)
        with self._lock("::new"):
            slug = self.new_slug(query)
            brief = new_brief(slug, query, days, codes)
            self._write_brief(slug, brief)
        return brief

    def save_brief(self, slug: str, brief: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock(slug):
            brief["updated"] = utcnow()
            self._write_brief(slug, brief)
        return brief

    def mutate_brief(
        self, slug: str, change: Callable[[Dict[str, Any]], None]
    ) -> Dict[str, Any]:
        """Load, apply `change`, write — all under the brief lock. `change` may raise."""
        with self._lock(slug):
            brief = self.load_brief(slug)
            change(brief)
            brief["updated"] = utcnow()
            self._write_brief(slug, brief)
            return brief

    # -- delete ----------------------------------------------------------
    def delete_brief(self, slug: str) -> str:
        with self._lock(slug):
            source = self.brief_dir(slug)
            if not source.is_dir():
                raise BriefNotFound(slug)
            target = self.trash_dir / f"{slug}-{int(time.time())}"
            while target.exists():
                target = Path(f"{target}x")
            os.rename(source, target)
            return target.name

    def purge_trash(self, days: int = 7) -> int:
        cutoff = time.time() - days * 86400
        removed = 0
        if not self.trash_dir.is_dir():
            return 0
        for entry in self.trash_dir.iterdir():
            if not entry.is_dir() or _trash_stamp(entry) > cutoff:
                continue
            shutil.rmtree(entry, ignore_errors=True)
            removed += 1
        return removed


def _trash_stamp(entry: Path) -> float:
    tail = entry.name.rsplit("-", 1)[-1]
    if tail.isdigit():
        return float(tail)
    return entry.stat().st_mtime
