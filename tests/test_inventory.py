import json
import shutil
from types import SimpleNamespace

import pandas as pd

from stormdb_catalog import inventory
from stormdb_catalog.extract import parse_filteredseries


def test_summarize(fixtures):
    series = parse_filteredseries((fixtures / "filteredseries.txt").read_text())
    row = inventory.summarize("MEG_vision", series)
    assert row["modalities"] == "MEG|MR"
    assert row["n_subjects_with_data"] == 3
    assert row["n_series"] == 5
    assert (row["n_subj_MEG"], row["n_subj_MR"], row["n_subj_MEG_and_MR"]) == (2, 2, 1)
    names = json.loads(row["series_names"])
    assert names["MEG"] == ["emptyroom", "gamma_raw", "rest_raw"]


def test_summarize_strips_numeric_prefix():
    row = inventory.summarize(
        "p", [{"subjectcode": "1", "modality": "MR", "seriename": "0003_t1"}]
    )
    assert json.loads(row["series_names"]) == {"MR": ["t1"]}


def test_run(fixtures, tmp_path, monkeypatch):
    shutil.copy(fixtures / "catalog" / "projects.csv", tmp_path)
    (tmp_path / "loginfile").write_text("login=abc")
    good = parse_filteredseries((fixtures / "filteredseries.txt").read_text())
    seen = []

    def fake_fetch(name, login_code, extract_url):
        seen.append((name, login_code, extract_url))
        if name == "old_audio":
            raise RuntimeError("boom")
        return [dict(s) for s in good]

    monkeypatch.setattr(inventory, "fetch_series", fake_fetch)
    args = SimpleNamespace(
        out=tmp_path, login_file=tmp_path / "loginfile", extract_url="URL/", delay=0
    )
    inventory.run(args)

    assert seen[0] == ("MEG_vision", "login=abc", "URL/")
    inv = pd.read_csv(tmp_path / "inventory.csv").set_index("name")
    assert inv.loc["MEG_vision", "n_subj_MEG_and_MR"] == 1
    assert inv.loc["old_audio", "inventory_error"] == "boom"
    series = pd.read_csv(tmp_path / "series.csv")
    assert list(series.columns) == [
        "project",
        "subjectcode",
        "study",
        "modality",
        "serieno",
        "seriename",
        "path",
    ]
    assert len(series) == 10  # two successful projects x 5 series
