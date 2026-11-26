"""
Tests for the Insights API (checkpoint 11): cleaning the animal-bites data,
the chart numbers and the endpoint.
"""

from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient

from backend.app import AppSettings, create_app
from backend.insights import DEFAULT_CSV, InsightsCache, compute_insights, load_bites
from tests.test_api import LOCAL

HEADER = ("bite_date,SpeciesIDDesc,BreedIDDesc,GenderIDDesc,color,vaccination_yrs,vaccination_date,victim_zip,"
          "AdvIssuedYNDesc,WhereBittenIDDesc,quarantine_date,DispositionIDDesc,head_sent_date,release_date,ResultsIDDesc")
ROWS = [
    "2015-05-03 00:00:00,DOG,PIT BULL,MALE,,1,2014-06-01 00:00:00,40214,NO,HEAD,,RELEASED,,,NEGATIVE",
    "2015-05-10 00:00:00,DOG,GERM SHEPHERD,FEMALE,,,,40214,,BODY,,,,,",
    "2016-05-12 00:00:00,DOG,BLACK LAB,,,,,40214,,BODY,,,,,POSITIVE",
    "2016-01-02 00:00:00,DOG,LABRADOR RETRIV,MALE,,3,,40214,,BODY,,,,,",
    "5013-01-02 00:00:00,DOG,OTHER,MALE,,,,40214,,,,,,,",            # impossible year
    "2015-07-04 00:00:00,CAT,,,,,,40214,,BODY,,,,,",
    ",,,,,,,,,,,,,,",
]


@pytest.fixture()
def csv(tmp_path):
    path = tmp_path / "bites.csv"
    path.write_text("\n".join([HEADER, *ROWS]) + "\n")
    return path


def test_load_bites_cleans_columns(csv):
    df = load_bites(csv)
    assert len(df) == 7 and df["species"].tolist().count("DOG") == 5
    assert df["date"].isna().sum() == 2                                  # bad year + empty row
    assert df["breed"].tolist()[:4] == ["Pit Bull", "German Shepherd", "Labrador Retriever", "Labrador Retriever"]
    assert df["breed"].isna().tolist()[4]                                # "OTHER" counts as unknown
    assert df["vaccinated"].tolist()[:4] == [True, False, False, True]   # date or years recorded


def test_compute_insights(csv):
    ins = compute_insights(load_bites(csv))
    s = ins["summary"]
    assert (s["records"], s["dog_records"], s["dated_dog_records"]) == (7, 5, 4)
    assert s["rabies_tested"] == 2 and s["rabies_positive"] == 1
    assert s["head_bite_share"] == 0.2 and s["busiest_month"] == "May"

    c = ins["charts"]
    assert dict(zip(c["breeds"]["labels"], c["breeds"]["values"])) == {
        "Labrador Retriever": 2, "Pit Bull": 1, "German Shepherd": 1}
    # May has 2 bites in 2015 and 1 in 2016 -> average 1.5 per year that had May bites
    assert c["by_month"]["labels"][4] == "May" and c["by_month"]["values"][4] == 1.5
    assert c["by_year"]["labels"][0] == "2010" and len(c["by_year"]["labels"]) == 8
    assert dict(zip(c["by_year"]["labels"], c["by_year"]["values"]))["2015"] == 2
    assert dict(zip(c["species"]["labels"], c["species"]["values"])) == {"Dog": 5, "Cat": 1, "Not recorded": 1}
    for chart in c.values():
        assert len(chart["labels"]) == len(chart["values"]) and chart["title"]
    json.dumps(ins)                                                     # plain JSON types only


def test_cache_reloads_only_when_file_changes(csv):
    cache = InsightsCache(csv)
    first = cache.get()
    assert cache.get() is first
    csv.write_text("\n".join([HEADER, *ROWS, ROWS[0]]) + "\n")
    os.utime(csv, ns=(1, 10**18))                                       # make sure the time changes
    assert cache.get()["summary"]["dog_records"] == 6


@pytest.mark.skipif(not DEFAULT_CSV.exists(), reason="bites dataset not in the repo")
def test_real_dataset():
    s = InsightsCache().get()["summary"]
    assert s["records"] == 9003 and s["dog_records"] == 7029


def test_insights_api(tmp_path, csv):
    def client(path):
        return TestClient(create_app(AppSettings(storage_dir=str(tmp_path / "st"), media_dir=str(tmp_path / "m"),
                                                 bites_csv=str(path))), client=LOCAL)

    with client(csv) as c:
        r = c.get("/api/insights")
        assert r.status_code == 200 and r.json()["summary"]["dog_records"] == 5
    with client(tmp_path / "missing.csv") as c:
        assert c.get("/api/insights").status_code == 404
    with TestClient(create_app(AppSettings(storage_dir=str(tmp_path / "st2"), media_dir=str(tmp_path / "m"),
                                           bites_csv=str(csv), access_token="secret")),
                    client=("192.168.1.50", 5000)) as c:
        assert c.get("/api/insights").status_code == 401                # data needs the token from other devices
        assert c.get("/api/insights", headers={"X-Access-Token": "secret"}).status_code == 200
