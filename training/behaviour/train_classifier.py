"""
Train the behaviour classifier from the feature table made by extract_features.py.

    python -m training.behaviour.train_classifier --data datasets/behaviour_features.csv

What it does
    1. Cross-validation split **by clip**: all rows of one clip are either in
       training or in testing, never both. Rows from the same clip are almost
       identical, so a random row split would report a fake, too-high accuracy.
    2. Prints accuracy, macro F1, a per-class report and the confusion matrix,
       and compares with the old rule (speed thresholds in backend/behaviour.py).
    3. Trains the final model on all rows and saves
           models/behaviour.joblib   the model (the server loads it at start)
           models/behaviour.json     the test results (shown on the dashboard)

The model is a random forest: works well on a few hundred rows, needs no
feature scaling, and its feature importances are easy to explain in a viva.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.model_selection import StratifiedGroupKFold, StratifiedKFold, cross_val_predict

from backend.behaviour import classify
from backend.features import FEATURE_NAMES, to_activity

ROOT = Path(__file__).resolve().parents[2]


def make_model(seed: int = 0) -> RandomForestClassifier:
    return RandomForestClassifier(n_estimators=200, min_samples_leaf=2, class_weight="balanced",
                                  random_state=seed, n_jobs=-1)


def load(paths: list[Path]) -> pd.DataFrame:
    df = pd.concat([pd.read_csv(p) for p in paths], ignore_index=True)
    missing = [c for c in ["clip", "label"] + FEATURE_NAMES if c not in df.columns]
    if missing:
        raise SystemExit(f"Columns missing from the feature table: {missing}")
    df = df.dropna(subset=FEATURE_NAMES)
    df["label"] = df["label"].astype(str).str.upper()
    return df


def evaluate(df: pd.DataFrame, seed: int = 0) -> dict:
    x, y, groups = df[FEATURE_NAMES].to_numpy(), df["label"].to_numpy(), df["clip"].to_numpy()
    labels = sorted(df["label"].unique())
    clips_per_label = df.groupby("label")["clip"].nunique()
    folds = int(min(5, clips_per_label.min()))
    if folds >= 2:
        cv = StratifiedGroupKFold(n_splits=folds, shuffle=True, random_state=seed)
        split = f"{folds}-fold, grouped by clip"
        pred = cross_val_predict(make_model(seed), x, y, groups=groups, cv=cv)
    else:
        # Only one clip for some label: we can't keep clips apart. Results will look too good.
        folds = int(min(5, df["label"].value_counts().min()))
        if folds < 2:
            raise SystemExit("Need at least 2 rows per label (better: 2+ clips per label).")
        cv = StratifiedKFold(n_splits=folds, shuffle=True, random_state=seed)
        split = f"{folds}-fold by row (WARNING: only 1 clip for some label, results are optimistic)"
        pred = cross_val_predict(make_model(seed), x, y, cv=cv)

    out = {
        "split": split,
        "accuracy": round(float(accuracy_score(y, pred)), 4),
        "macro_f1": round(float(f1_score(y, pred, average="macro")), 4),
        "labels": labels,
        "confusion_matrix": confusion_matrix(y, pred, labels=labels).tolist(),
        "per_class": {k: {m: round(v, 4) for m, v in d.items() if m != "support"} | {"support": int(d["support"])}
                      for k, d in classification_report(y, pred, labels=labels, output_dict=True,
                                                        zero_division=0).items() if k in labels},
    }

    # The old rule-based method, on the same rows, for comparison (3 activities only).
    true_act = np.array([to_activity(l) for l in y], dtype=object)
    keep = true_act != None  # noqa: E711  (elementwise)
    if keep.any():
        rule = np.array([classify(s) for s in df["net_speed"].to_numpy()[keep]])
        model_act = np.array([to_activity(p) or p for p in pred[keep]])
        out["vs_rule_baseline"] = {
            "rows": int(keep.sum()),
            "rule_accuracy": round(float((rule == true_act[keep]).mean()), 4),
            "model_accuracy": round(float((model_act == true_act[keep]).mean()), 4),
        }
    return out


def print_report(r: dict, n_rows: int, n_clips: int) -> None:
    print(f"\n{n_rows} rows from {n_clips} clips   split: {r['split']}")
    print(f"accuracy {r['accuracy']:.3f}   macro F1 {r['macro_f1']:.3f}\n")
    width = max(len(l) for l in r["labels"]) + 2
    print("per class".ljust(width), "precision  recall  f1     n")
    for label, m in r["per_class"].items():
        print(label.ljust(width), f"{m['precision']:.3f}      {m['recall']:.3f}   {m['f1-score']:.3f}  {m['support']}")
    print("\nconfusion matrix (rows = true, columns = predicted)")
    print("".ljust(width) + "".join(l[:8].rjust(9) for l in r["labels"]))
    for label, row in zip(r["labels"], r["confusion_matrix"]):
        print(label.ljust(width) + "".join(str(v).rjust(9) for v in row))
    if "vs_rule_baseline" in r:
        b = r["vs_rule_baseline"]
        print(f"\nRESTING/WALKING/RUNNING on {b['rows']} rows: speed-threshold rule {b['rule_accuracy']:.3f}"
              f"  vs  classifier {b['model_accuracy']:.3f}")


def main(argv=None) -> dict:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", type=Path, nargs="+", default=[ROOT / "datasets" / "behaviour_features.csv"])
    p.add_argument("--out", type=Path, default=ROOT / "models" / "behaviour.joblib")
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args(argv)

    import joblib

    df = load(args.data)
    if df["label"].nunique() < 2:
        raise SystemExit("Need clips of at least 2 different labels.")
    report = evaluate(df, args.seed)
    print_report(report, len(df), df["clip"].nunique())

    model = make_model(args.seed).fit(df[FEATURE_NAMES].to_numpy(), df["label"].to_numpy())
    importance = sorted(zip(FEATURE_NAMES, model.feature_importances_), key=lambda kv: -kv[1])
    print("\nmost useful features: " + ", ".join(f"{k} {v:.2f}" for k, v in importance[:5]))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "features": FEATURE_NAMES, "labels": report["labels"]}, args.out)
    meta = {"trained": time.strftime("%Y-%m-%d %H:%M"), "rows": int(len(df)),
            "clips": int(df["clip"].nunique()), **report,
            "feature_importance": {k: round(float(v), 4) for k, v in importance}}
    args.out.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"\nSaved {args.out} and {args.out.with_suffix('.json').name}. Restart the server to use it.")
    return meta


if __name__ == "__main__":
    main()
