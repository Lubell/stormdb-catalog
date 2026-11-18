import math

import pytest

from stormdb_catalog.projects import (
    clean_cookie,
    compare_project_lists,
    format_changes,
    is_login_page,
    parse_list_header,
    parse_project_info,
    parse_project_list,
)


def test_parse_project_list(fixtures):
    rows = parse_project_list((fixtures / "listprojects.html").read_text())
    assert [r["project_id"] for r in rows] == [
        101,
        102,
        103,
    ]  # header, totals and short rows skipped
    first = rows[0]
    assert first["name"] == "MEG_vision"
    assert first["responsible"] == "A. Researcher"
    assert first["n_subjects"] == 24
    assert (first["start_date"], first["end_date"], first["latest_activity"]) == (
        "2015-01-10",
        "2020-12-31",
        "2019-06-01",
    )


def test_parse_project_list_missing_values(fixtures):
    pd_motor = parse_project_list((fixtures / "listprojects.html").read_text())[2]
    assert math.isnan(pd_motor["n_subjects"])
    assert pd_motor["start_date"] == "2018-05-05"
    assert pd_motor["end_date"] == "" and pd_motor["latest_activity"] == ""


def test_parse_project_info(fixtures):
    info = parse_project_info((fixtures / "projectinfo.html").read_text())
    assert info["description"] == (
        "MEG and MRI study of visual gamma oscillations in V1.\n"
        "Healthy adults, passive viewing of gratings."
    )
    assert info["expired"] is True
    assert info["data_type"] == "Human (Anomymized)"
    assert (info["n_users_filesystem"], info["n_users_database"]) == (9, 2)
    assert (info["disk_raw_mb"], info["disk_scratch_mb"], info["disk_aux_mb"]) == (
        18602.0,
        5036.0,
        0.0,
    )
    assert info["n_documents"] == 3
    # rows from other panels (e.g. Subjects "Id: | Name:") are ignored
    assert set(info) == {
        "description",
        "expired",
        "data_type",
        "n_users_filesystem",
        "n_users_database",
        "disk_raw_mb",
        "disk_scratch_mb",
        "disk_aux_mb",
        "n_documents",
    }


def test_parse_project_info_no_description_not_expired():
    html = """<div class="panel"><h3 class="panel-title">Project information</h3>
    <table><tr><td>Data:</td><td>Animal</td></tr>
    <tr><td>End date:</td><td></td></tr></table></div>"""
    info = parse_project_info(html)
    assert info == {
        "description": "",
        "expired": False,
        "data_type": "Animal",
        "n_documents": None,
    }


def test_parse_project_info_unexpected_page():
    assert parse_project_info("<p>nothing here</p>") == {
        "description": "",
        "expired": False,
        "n_documents": None,
    }


def test_login_page_detection():
    assert is_login_page("<html><head><title>Login</title></head></html>")
    assert not is_login_page("<html><head><title></title></head></html>")


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("PHPSESSID=abc123", "PHPSESSID=abc123"),
        ("  Cookie: PHPSESSID=abc123; x=y \n", "PHPSESSID=abc123; x=y"),
    ],
)
def test_clean_cookie(raw, clean):
    assert clean_cookie(raw) == clean


@pytest.mark.parametrize(
    "raw", [None, "", "abc123def456", "\x1b[D\x1b[D\x1b[C\x1b[A\x1b[D", "a=b\x1b[D"]
)
def test_clean_cookie_rejects(raw):
    with pytest.raises(SystemExit):
        clean_cookie(raw)


def _anonymize_102_add_105_drop_103(html):
    html = html.replace(
        "<td>2011-11-11</td><td>Yes</td>", "<td>2011-11-11</td><td>No (anonymized)</td>"
    )
    html = html.replace("<td>103</td>", "<td>105</td>").replace("pd_motor", "new_proj")
    return html


def test_compare_project_lists(fixtures):
    html = (fixtures / "listprojects.html").read_text()
    stored = parse_project_list(html)
    new_html = _anonymize_102_add_105_drop_103(html)
    diff = compare_project_lists(
        stored, parse_project_list(new_html), parse_list_header(new_html)
    )
    assert [r["project_id"] for r in diff["new"]] == [105]
    assert [r["project_id"] for r in diff["removed"]] == [103]
    [(row, diffs)] = diff["changed"]
    assert row["project_id"] == 102
    assert diffs == [("Personal data", "Yes", "No (anonymized)")]
    out = format_changes(diff)
    assert "Personal data: 'Yes' -> 'No (anonymized)'" in out
    assert "105  new_proj" in out and "103  pd_motor" in out


def test_compare_project_lists_labels_without_header(fixtures):
    html = (fixtures / "listprojects.html").read_text()
    stored = parse_project_list(html)
    diff = compare_project_lists(
        stored, parse_project_list(_anonymize_102_add_105_drop_103(html))
    )
    assert diff["changed"][0][1] == [("Personal data", "Yes", "No (anonymized)")]


def test_compare_project_lists_no_changes(fixtures):
    rows = parse_project_list((fixtures / "listprojects.html").read_text())
    assert (
        format_changes(compare_project_lists(rows, rows))
        == "No changes in the project list."
    )


def test_run_changes_is_read_only(fixtures, tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace

    import pandas as pd
    from conftest import FakeResponse

    from stormdb_catalog import projects

    html = (fixtures / "listprojects.html").read_text()
    pd.DataFrame(parse_project_list(html)).to_csv(
        tmp_path / "projects.csv", index=False
    )
    before = (tmp_path / "projects.csv").read_bytes()

    class FakeSession:
        def get(self, url, timeout=None):
            assert url == projects.LIST_URL  # only the list page is fetched
            return FakeResponse(_anonymize_102_add_105_drop_103(html))

    monkeypatch.setattr(projects, "_session", lambda cookie: FakeSession())
    projects.run_changes(SimpleNamespace(out=tmp_path, cookie="PHPSESSID=x"))
    out = capsys.readouterr().out
    assert "Changed (1):" in out and "No (anonymized)" in out
    assert (tmp_path / "projects.csv").read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["projects.csv"]
