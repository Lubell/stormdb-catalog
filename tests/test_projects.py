import math

from stormdb_catalog.projects import parse_project_info, parse_project_list


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
    assert [r["expired_style"] for r in rows] == [False, True, False]


def test_parse_project_list_missing_values(fixtures):
    pd_motor = parse_project_list((fixtures / "listprojects.html").read_text())[2]
    assert math.isnan(pd_motor["n_subjects"])
    assert pd_motor["start_date"] == "2018-05-05"
    assert pd_motor["end_date"] == "" and pd_motor["latest_activity"] == ""


def test_parse_project_info(fixtures):
    info = parse_project_info((fixtures / "projectinfo.html").read_text())
    assert info["description"].startswith("MEG and MRI study of visual gamma")
    assert info["human_data"] == "Yes"
    assert info["anonymized"] == ""  # empty field must not swallow the next label
    assert info["expired"] == "No"
    assert info["esdh_journal"] == "1-10-72-1-15"
    assert "missing_approvals" not in info
    assert info["n_documents"] == 3


def test_parse_project_info_without_documents():
    assert parse_project_info("<p>Description:</p><p>x</p>")["n_documents"] is None
