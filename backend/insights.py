"""
Insights from the animal-bites dataset (data/tabular/Health_AnimalBites.csv)
for the dashboard's Insights page (PLAN 2.3 #7 and 3.4).

The file has 9,003 bite reports (7,029 by dogs) from Louisville, Kentucky,
2010-2017. It is not Indian street-dog data, so the page shows it as
background on dog bites in general: when bites happen, which body parts,
vaccination records and lab results.

Every chart is returned as {"title", "labels", "values", "note"} so the
frontend can hand it straight to Chart.js. The CSV is read once and cached;
it changes only if someone replaces the file.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV = ROOT / "data" / "tabular" / "Health_AnimalBites.csv"

# The data has a few typing mistakes in the date (years 1952, 2101, 5013...).
# The real reports run 2010-2017; earlier years have only a handful of rows.
FIRST_YEAR, LAST_YEAR = 2010, 2017

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Spelling variants in the breed column that are clearly the same breed.
BREED_NAMES = {
    "GERM SHEPHERD": "German Shepherd", "LABRADOR RETRIV": "Labrador Retriever", "BLACK LAB": "Labrador Retriever",
    "GOLDEN LAB": "Labrador Retriever", "CHOCOLATE LAB.": "Labrador Retriever", "CHICHAUHUA": "Chihuahua",
    "GOLD RETRIEVER": "Golden Retriever", "SIBERAN HUSKY": "Husky", "HUSKY": "Husky",
    "BULL DOG": "Bulldog", "ENGLISH BULLDOG": "Bulldog", "AM BULLDOG": "American Bulldog",
    "AMER. BULL DOG": "American Bulldog", "COCKER SPAINEL": "Cocker Spaniel", "MALTASE": "Maltese",
    "MASTIF": "Mastiff", "ENG. MASTIFF": "Mastiff", "MIN PIN": "Miniature Pinscher",
    "DOTSON": "Dachshund", "WEINER DOG": "Dachshund", "BORDER COLLIE M": "Border Collie",
    "GREAT PYRENEESE": "Great Pyrenees", "PYRENES": "Great Pyrenees", "BICHON FRESE": "Bichon Frise",
    "ST BERNARD": "Saint Bernard", "ALASK. MALAMUTE": "Alaskan Malamute", "MALAMUTE": "Alaskan Malamute",
    "WELSH CORGI": "Corgi", "BASANJI": "Basenji", "BESINJI": "Basenji", "BERNESEN MT.": "Bernese Mountain Dog",
    "BRITNEY SPANIEL": "Brittany Spaniel", "NEW FOUNDLAND": "Newfoundland", "SHAR-PEI": "Shar-Pei",
    "BLUE HEELER": "Cattle Dog", "RED HEELER": "Cattle Dog", "HEELER": "Cattle Dog", "CATTLE DOG": "Cattle Dog",
    "TOY POODLE": "Poodle", "STAN POODLE": "Poodle", "FOX TERRIER MIX": "Fox Terrier",
}


def _breed(raw) -> str | None:
    if not isinstance(raw, str) or not raw.strip() or raw.strip().upper() == "OTHER":
        return None
    raw = raw.strip().upper()
    return BREED_NAMES.get(raw, raw.title())


def load_bites(path: str | Path = DEFAULT_CSV) -> pd.DataFrame:
    """All bite reports with tidy columns. Dates outside 2010-2017 become missing."""
    df = pd.read_csv(path, low_memory=False, dtype=str)
    out = pd.DataFrame()
    out["species"] = df.get("SpeciesIDDesc").fillna("UNKNOWN").str.strip().str.upper()
    date = pd.to_datetime(df.get("bite_date"), errors="coerce")
    date = date.where(date.dt.year.between(FIRST_YEAR, LAST_YEAR))
    out["date"] = date
    out["breed"] = df.get("BreedIDDesc").map(_breed)
    out["gender"] = df.get("GenderIDDesc").fillna("UNKNOWN").str.upper()
    out["where"] = df.get("WhereBittenIDDesc").fillna("UNKNOWN").str.upper()
    vacc_date = pd.to_datetime(df.get("vaccination_date"), errors="coerce")
    out["vaccinated"] = vacc_date.notna() | pd.to_numeric(df.get("vaccination_yrs"), errors="coerce").notna()
    out["disposition"] = df.get("DispositionIDDesc").fillna("NOT RECORDED").str.upper()
    out["result"] = df.get("ResultsIDDesc").fillna("NOT TESTED").str.upper()
    return out


def _chart(title: str, counts: pd.Series, note: str = "", labels=None) -> dict:
    if labels is not None:
        counts = counts.reindex(labels, fill_value=0)
    return {"title": title, "labels": [str(x) for x in counts.index],
            "values": [int(v) for v in counts.values], "note": note}


def _pretty(series: pd.Series) -> pd.Series:
    """Upper-case category names to 'Title case', keeping counts."""
    series = series.copy()
    series.index = [str(i).capitalize() for i in series.index]
    return series


def compute_insights(df: pd.DataFrame, top_breeds: int = 10) -> dict:
    dogs = df[df["species"] == "DOG"]
    dated = dogs.dropna(subset=["date"])
    n = len(dogs)
    breed_known = dogs["breed"].notna()
    tested = dogs[dogs["result"].isin(["POSITIVE", "NEGATIVE"])]

    years = list(range(FIRST_YEAR, LAST_YEAR + 1))
    # Average bites per calendar month over the full years, so a month that
    # appears in more years doesn't look busier than it is.
    per_month = dated.groupby([dated["date"].dt.year, dated["date"].dt.month]).size()
    month_avg = per_month.groupby(level=1).mean().reindex(range(1, 13), fill_value=0)
    busiest = MONTHS[int(month_avg.idxmax()) - 1] if len(dated) else None
    head_share = (dogs["where"] == "HEAD").mean() if n else 0.0
    species = df["species"].replace({"UNKNOWN": "Not recorded"}).value_counts()

    summary = {
        "records": int(len(df)),
        "dog_records": int(n),
        "dog_share": round(n / len(df), 3) if len(df) else 0.0,
        "years": [FIRST_YEAR, LAST_YEAR],
        "dated_dog_records": int(len(dated)),
        "breed_known_share": round(float(breed_known.mean()), 3) if n else 0.0,
        "vaccination_recorded_share": round(float(dogs["vaccinated"].mean()), 3) if n else 0.0,
        "head_bite_share": round(float(head_share), 3),
        "rabies_tested": int(len(tested)),
        "rabies_positive": int((tested["result"] == "POSITIVE").sum()),
        "busiest_month": busiest,
        "source": "Louisville Metro (Kentucky, USA) animal bite reports",
    }

    charts = {
        "species": _chart("Bites by animal", _pretty(species).head(8),
                          "Dogs cause most reported bites."),
        "by_year": _chart("Dog bites per year",
                          dated["date"].dt.year.value_counts(), "", labels=years),
        "by_month": {**_chart("Average dog bites per month", month_avg.round(1), "Averaged over 2010-2017."),
                     "labels": MONTHS, "values": [round(float(v), 1) for v in month_avg.values]},
        "by_weekday": _chart("Dog bites by day of week",
                             dated["date"].dt.dayofweek.value_counts().rename(index=dict(enumerate(WEEKDAYS))),
                             "", labels=WEEKDAYS),
        "breeds": _chart(f"Top {top_breeds} breeds (where recorded)",
                         dogs.loc[breed_known, "breed"].value_counts().head(top_breeds),
                         f"Breed is recorded for {breed_known.mean():.0%} of dog bites. More bites by a breed "
                         "can simply mean the breed is more common, so this is not a danger ranking."),
        "body_part": _chart("Where people were bitten", _pretty(dogs["where"].value_counts())),
        "gender": _chart("Sex of the dog", _pretty(dogs["gender"].value_counts())),
        "vaccination": _chart("Dog's vaccination on record",
                              dogs["vaccinated"].map({True: "Recorded", False: "No record"}).value_counts(),
                              "'No record' means the report has no vaccination date, not that the dog was unvaccinated."),
        "rabies_result": _chart("Rabies test result", _pretty(dogs["result"].value_counts()),
                                "Only a few dogs are tested; this is why the old rabies classifier was dropped."),
        "outcome": _chart("What happened to the dog", _pretty(dogs["disposition"].value_counts())),
    }
    return {"summary": summary, "charts": charts}


class InsightsCache:
    """Reads the CSV on first use and again only when the file changes."""

    def __init__(self, path: str | Path = DEFAULT_CSV):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._key = None
        self._data = None

    def get(self) -> dict:
        stat = self.path.stat()                  # FileNotFoundError if missing
        key = (stat.st_mtime_ns, stat.st_size)
        with self._lock:
            if key != self._key:
                self._data = compute_insights(load_bites(self.path))
                self._key = key
            return self._data
