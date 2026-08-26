import json
import threading
import time
from pathlib import Path

import pytest

from core.schema import BriefNotFound, slugify
from core.storage import Storage


@pytest.fixture()
def store(tmp_path: Path) -> Storage:
    return Storage(tmp_path / "data")


def test_roundtrip(store: Storage) -> None:
    brief = store.create_brief("Samsung Electronics", period_days=30, lang=["en"])
    assert brief["slug"] == "samsung-electronics"
    assert brief["schema"] == 1 and brief["status"] == "empty"
    assert brief["articles"] == [] and brief["synthesis"] is None
    assert brief["period_days"] == 30 and brief["lang"] == ["en"]

    loaded = store.load_brief(brief["slug"])
    assert loaded["query"] == "Samsung Electronics"
    summaries = store.list_briefs()
    assert [s["slug"] for s in summaries] == [brief["slug"]]
    assert summaries[0]["article_count"] == 0
    assert summaries[0]["sentiment_counts"] == {
        "positive": 0,
        "negative": 0,
        "neutral": 0,
    }
    assert "articles" not in summaries[0]


def test_defaults_and_slug_dedupe(store: Storage) -> None:
    first = store.create_brief("Same Query")
    assert first["period_days"] == 90 and first["lang"] == ["ko", "en"]
    second = store.create_brief("Same Query")
    third = store.create_brief("Same Query")
    assert [first["slug"], second["slug"], third["slug"]] == [
        "same-query",
        "same-query-2",
        "same-query-3",
    ]
    assert slugify("....") == "brief"
    assert store.create_brief("한국어")["slug"] == "brief"


@pytest.mark.parametrize("bad", ["../x", "a/b", "Uppercase", "x" * 65, "", "a b", ".."])
def test_slug_traversal_rejected(store: Storage, bad: str) -> None:
    with pytest.raises(ValueError):
        store.brief_dir(bad)
    with pytest.raises(ValueError):
        store.load_brief(bad)
    with pytest.raises(ValueError):
        store.delete_brief(bad)


def test_create_validation(store: Storage) -> None:
    for kwargs in (
        {"query": ""},
        {"query": "   "},
        {"query": "x" * 201},
        {"query": 5},
        {"query": None},
        {"query": "ok", "period_days": 45},
        {"query": "ok", "period_days": True},
        {"query": "ok", "lang": ["fr"]},
        {"query": "ok", "lang": []},
    ):
        with pytest.raises(ValueError):
            store.create_brief(**kwargs)
    assert store.create_brief("x" * 200)["query"] == "x" * 200


def test_atomic_write_leaves_no_tmp_and_rotates_bak(store: Storage) -> None:
    slug = store.create_brief("Rotate Me")["slug"]
    brief = store.load_brief(slug)
    brief["status"] = "collected"
    store.save_brief(slug, brief)
    brief["status"] = "analyzed"
    store.save_brief(slug, brief)

    folder = store.brief_dir(slug)
    assert not list(folder.glob("*.tmp"))
    assert json.loads((folder / "brief.json").read_text())["status"] == "analyzed"
    assert json.loads((folder / "brief.json.bak").read_text())["status"] == "collected"


def test_corrupt_recovers_from_bak(store: Storage) -> None:
    slug = store.create_brief("Corrupt Me")["slug"]
    brief = store.load_brief(slug)
    brief["articles"] = [{"id": "a1", "title": "kept", "sentiment": "positive"}]
    store.save_brief(slug, brief)
    store.save_brief(slug, brief)  # ensure a .bak exists

    (store.brief_dir(slug) / "brief.json").write_text("{not json", encoding="utf-8")
    recovered = store.load_brief(slug)
    assert recovered["recovered"] is True
    assert recovered["articles"][0]["title"] == "kept"
    summary = store.list_briefs()[0]
    assert summary["recovered"] is True
    assert summary["sentiment_counts"]["positive"] == 1

    # a rewrite drops the transient flag from disk
    store.save_brief(slug, recovered)
    on_disk = json.loads((store.brief_dir(slug) / "brief.json").read_text())
    assert "recovered" not in on_disk


def test_corrupt_both_copies_preserves_file_and_restarts_empty(store: Storage) -> None:
    slug = store.create_brief("Total Loss")["slug"]
    brief = store.load_brief(slug)
    brief["articles"] = [{"id": "a1", "title": "gone"}]
    store.save_brief(slug, brief)
    store.save_brief(slug, brief)

    folder = store.brief_dir(slug)
    (folder / "brief.json").write_text("]]] broken", encoding="utf-8")
    (folder / "brief.json.bak").write_text("also broken {", encoding="utf-8")

    restarted = store.load_brief(slug)
    assert restarted["data_loss"] is True
    assert restarted["status"] == "empty" and restarted["articles"] == []
    assert restarted["slug"] == slug

    preserved = list(folder.glob("brief.json.corrupt-*"))
    assert len(preserved) == 1
    assert preserved[0].read_text() == "]]] broken"

    # the fresh file is on disk and readable, without the transient flag
    on_disk = json.loads((folder / "brief.json").read_text())
    assert on_disk["status"] == "empty" and "data_loss" not in on_disk
    assert store.list_briefs()[0]["status"] == "empty"


def test_unknown_schema_version_is_read_only(store: Storage) -> None:
    slug = store.create_brief("From The Future")["slug"]
    path = store.brief_dir(slug) / "brief.json"
    data = json.loads(path.read_text())
    data["schema"] = 99
    path.write_text(json.dumps(data), encoding="utf-8")
    assert store.load_brief(slug)["read_only"] is True


def test_missing_brief(store: Storage) -> None:
    with pytest.raises(BriefNotFound):
        store.load_brief("ghost")
    with pytest.raises(BriefNotFound):
        store.delete_brief("ghost")


def test_concurrent_writes_serialize(store: Storage) -> None:
    slug = store.create_brief("Race")["slug"]
    errors: list[Exception] = []

    def bump(field: str, times: int) -> None:
        try:
            for i in range(times):
                store.mutate_brief(slug, lambda brief, f=field, v=i: brief.update({f: v}))
        except Exception as exc:  # pragma: no cover - surfaced via assert
            errors.append(exc)

    threads = [
        threading.Thread(target=bump, args=("alpha", 40)),
        threading.Thread(target=bump, args=("beta", 40)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    final = store.load_brief(slug)
    assert "recovered" not in final and "data_loss" not in final
    assert final["alpha"] == 39 and final["beta"] == 39
    assert final["query"] == "Race"


def test_delete_moves_to_trash_and_purge_expires(store: Storage) -> None:
    slug = store.create_brief("Trash Me")["slug"]
    name = store.delete_brief(slug)
    assert not store.brief_dir(slug).exists()
    assert (store.trash_dir / name).is_dir()
    with pytest.raises(BriefNotFound):
        store.delete_brief(slug)

    old = store.trash_dir / f"stale-{int(time.time()) - 8 * 86400}"
    old.mkdir()
    (old / "brief.json").write_text("{}", encoding="utf-8")

    assert store.purge_trash(days=7) == 1
    assert not old.exists()
    assert (store.trash_dir / name).is_dir()

    assert store.purge_trash(days=0) == 1
    assert not (store.trash_dir / name).exists()
