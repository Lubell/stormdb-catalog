import json
import shutil
from types import SimpleNamespace

import pandas as pd

from stormdb_catalog import tagging


def test_keyword_tags():
    tags = tagging.keyword_tags(
        "Resting state MEG in Parkinson patients, finger tapping"
    )
    assert tags["resting_state"] and tags["motor"] and tags["clinical"]
    assert not tags["vision"] and not tags["audition"]
    assert not any(tagging.keyword_tags(None).values())


def test_run_keywords(fixtures, tmp_path):
    for f in ["projects.csv", "inventory.csv"]:
        shutil.copy(fixtures / "catalog" / f, tmp_path)
    tagging.run(SimpleNamespace(out=tmp_path, method="keywords", model=None))
    tags = (
        pd.read_csv(tmp_path / "tags.csv").set_index("name")["domain"].map(json.loads)
    )
    assert "vision" in tags["MEG_vision"]
    assert "audition" in tags["old_audio"]
    assert {"motor", "clinical"} <= set(tags["pd_motor"])
