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
