from types import SimpleNamespace

import pandas as pd
import pytest
from conftest import FakeResponse

from stormdb_catalog import inventory, sync
from stormdb_catalog.projects import (
    INFO_URL,
    LIST_URL,
    parse_project_info,
    parse_project_list,
)


def _changed_list(html):
    """102 anonymized, 103 removed, 105 added."""
    html = html.replace(
        "<td>2011-11-11</td><td>Yes</td>", "<td>2011-11-11</td><td>No (anonymized)</td>"
    )
    return html.replace("<td>103</td>", "<td>105</td>").replace("pd_motor", "new_proj")


def _series(project):
    return {
        "project": project,
        "subjectcode": "0001",
        "study": "20200101_000000",
        "modality": "MR",
        "serieno": "001",
        "seriename": f"{project}_old",
        "path": f"/projects/{project}/raw/0001/20200101_000000/MR/001.{project}_old/files",
    }


@pytest.fixture
def catalog(fixtures, tmp_path):
    """A stored catalog for the fixture list, with marker values to spot rewrites."""
    list_html = (fixtures / "listprojects.html").read_text()
    info = parse_project_info((fixtures / "projectinfo.html").read_text())
    rows = [{**p, **info} for p in parse_project_list(list_html)]
    for p in rows:
        p["description"] = f"STORED {p['project_id']}"
    pd.DataFrame(rows).to_csv(tmp_path / "projects.csv", index=False)
    names = [p["name"] for p in rows]
    pd.DataFrame([_series(n) for n in names]).to_csv(
        tmp_path / "series.csv", index=False
    )
    pd.DataFrame([inventory.summarize(n, [_series(n)]) for n in names]).to_csv(
        tmp_path / "inventory.csv", index=False
    )
    (tmp_path / "loginfile").write_text("login=abc")
    return SimpleNamespace(dir=tmp_path, list_html=list_html)


@pytest.fixture
def server(fixtures, monkeypatch):
    """Fake StormDb: list page, info pages and series; records what was fetched."""
    calls = SimpleNamespace(info=[], series=[], list_html=None)
    info_html = (fixtures / "projectinfo.html").read_text()

    class FakeSession:
        def get(self, url, timeout=None):
            if url == LIST_URL:
                return FakeResponse(calls.list_html)
            pid = int(url.rsplit("/", 1)[1])
            assert url == INFO_URL.format(pid=pid)
            calls.info.append(pid)
            return FakeResponse(info_html)

    def fake_fetch(name, login_code, extract_url):
        calls.series.append(name)
        new = _series(name)
        new["seriename"] = new["path"] = f"{name}_new"
        return [new]

    monkeypatch.setattr(sync, "_session", lambda cookie: FakeSession())
    monkeypatch.setattr(inventory, "fetch_series", fake_fetch)
    return calls


def _args(catalog, **kw):
    return SimpleNamespace(
        out=catalog.dir,
        cookie="PHPSESSID=x",
        login_file=catalog.dir / "loginfile",
        extract_url="URL/",
        delay=0,
        all_info=False,
        no_tag=False,
        **kw,
    )


def test_sync_refetches_only_changed(catalog, server, capsys):
    server.list_html = _changed_list(catalog.list_html)
    sync.run(_args(catalog))

    assert sorted(server.info) == [102, 105]
    assert sorted(server.series) == ["new_proj", "old_audio"]

    p = pd.read_csv(catalog.dir / "projects.csv").set_index("project_id")
    assert list(p.index) == [101, 102, 105]
    assert p.loc[101, "description"] == "STORED 101"  # untouched
    assert p.loc[102, "description"].startswith("MEG and MRI study")  # refetched
    assert "No (anonymized)" in p.loc[102, "raw_cells"]

    s = pd.read_csv(catalog.dir / "series.csv", dtype=str)
    assert sorted(s["project"]) == ["MEG_vision", "new_proj", "old_audio"]
    assert s.set_index("project").loc["MEG_vision", "seriename"] == "MEG_vision_old"
    assert s.set_index("project").loc["old_audio", "seriename"] == "old_audio_new"
    assert set(s["serieno"]) == {"001"}  # leading zeros survive the round trip

    inv = pd.read_csv(catalog.dir / "inventory.csv")
    assert list(inv["name"]) == ["MEG_vision", "old_audio", "new_proj"]  # list order
    tags = pd.read_csv(catalog.dir / "tags.csv")
    assert list(tags["name"]) == ["MEG_vision", "old_audio", "new_proj"]

    out = capsys.readouterr().out
    assert "Personal data: 'Yes' -> 'No (anonymized)'" in out
    assert "Updated catalog: 3 projects, 3 series" in out
    assert not list(catalog.dir.glob("*.tmp"))


def test_sync_up_to_date_writes_nothing(catalog, server, capsys):
    server.list_html = catalog.list_html
    before = {f.name: f.read_bytes() for f in catalog.dir.iterdir()}
    sync.run(_args(catalog))
    assert "Catalog is up to date." in capsys.readouterr().out
    assert {f.name: f.read_bytes() for f in catalog.dir.iterdir()} == before
    assert server.info == [] and server.series == []


def test_sync_all_info_catches_edits_missing_from_list(catalog, server, capsys):
    server.list_html = catalog.list_html  # no list changes
    args = _args(catalog)
    args.all_info = True
    sync.run(args)
    assert sorted(server.info) == [101, 102, 103]
    assert server.series == []  # series only follow list changes
    out = capsys.readouterr().out
    assert "Info page changed for 3 project(s) with no list change" in out
    p = pd.read_csv(catalog.dir / "projects.csv")
    assert not p["description"].str.startswith("STORED").any()


def test_sync_renamed_project_replaces_old_rows(catalog, server):
    server.list_html = catalog.list_html.replace("old_audio", "audio_renamed")
    sync.run(_args(catalog))
    assert server.series == ["audio_renamed"]
    s = pd.read_csv(catalog.dir / "series.csv", dtype=str)
    assert "old_audio" not in set(s["project"])
    inv = pd.read_csv(catalog.dir / "inventory.csv")
    assert list(inv["name"]) == ["MEG_vision", "audio_renamed", "pd_motor"]


def test_sync_needs_existing_catalog(tmp_path):
    with pytest.raises(SystemExit, match="run the projects and inventory stages"):
        sync.run(SimpleNamespace(out=tmp_path))
