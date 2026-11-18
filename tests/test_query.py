import pandas as pd
import pytest

from stormdb_catalog.cli import main


@pytest.fixture
def query(fixtures, capsys):
    def run(*argv):
        main(["--out", str(fixtures / "catalog"), "query", *argv])
        return capsys.readouterr().out

    return run


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        ([], {"MEG_vision", "old_audio", "pd_motor"}),
        (["--domain", "vision"], {"MEG_vision"}),
        (["--domain", "clinical"], {"pd_motor"}),
        (["--has", "MEG"], {"MEG_vision", "old_audio"}),
        (["--has", "MEG", "MR"], {"MEG_vision"}),
        (["--both-meg-mr", "1"], {"MEG_vision"}),
        (["--text", "parkinson|mismatch"], {"old_audio", "pd_motor"}),
    ],
)
def test_filters(query, argv, expected):
    out = query(*argv)
    assert f"{len(expected)} projects match" in out
    for name in ("MEG_vision", "old_audio", "pd_motor"):
        assert (name in out) == (name in expected)


def test_save(query, tmp_path):
    query("--has", "MR", "--save", str(tmp_path / "res.csv"))
    res = pd.read_csv(tmp_path / "res.csv")
    assert list(res["name"]) == ["MEG_vision", "pd_motor"]
    assert "description" in res.columns


def test_cards_fit_width_and_mark_expired(query):
    out = query("--width", "60")
    lines = out.splitlines()
    assert all(len(line) <= 60 for line in lines)
    assert "101  MEG_vision" in out
    assert "Tags: vision" in out  # JSON list rendered as plain text
    assert "Modalities: MEG, MR" in out
    assert "(1 MEG+MR)" in out


def test_cards_truncate_description_unless_full(fixtures, capsys, tmp_path):
    import shutil

    for f in ["projects.csv", "inventory.csv", "tags.csv"]:
        shutil.copy(fixtures / "catalog" / f, tmp_path)
    p = pd.read_csv(tmp_path / "projects.csv")
    p.loc[0, "description"] = "word " * 200
    p.loc[1, "description"] = None
    p["expired"] = [True, False, False]
    p.to_csv(tmp_path / "projects.csv", index=False)

    main(["--out", str(tmp_path), "query", "--width", "60"])
    short = capsys.readouterr().out
    assert short.count("word") < 50 and "…" in short
    assert "(no description)" in short
    assert "MEG_vision  [expired]" in short
    main(["--out", str(tmp_path), "query", "--width", "60", "--full"])
    assert capsys.readouterr().out.count("word") == 200


def test_table(query):
    out = query("--table", "--width", "60")
    lines = out.splitlines()
    assert lines[0].split() == ["ID", "Name", "Start", "Subj", "MEG+MR", "Modalities"]
    assert all(len(line) <= 60 for line in lines)
    row = next(line for line in lines if "MEG_vision" in line)
    assert "2015-01" in row and "MEG, MR" in row
