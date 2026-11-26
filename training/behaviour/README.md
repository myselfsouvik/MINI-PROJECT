# behaviour

Behaviour classifier (lying / sitting / standing / walking / running). Owner: Samaraho.

The backend already has a working pipeline for it, from labelled clips to the live dashboard. It uses movement features only, as a baseline. Improve it from here, for example by adding pose features or more labels.

## How it works

```
labelled clips ──► extract_features.py ──► features.csv ──► train_classifier.py ──► models/behaviour.joblib
 (one folder        (same YOLO + tracker      (one row per dog    (random forest,          + behaviour.json
  per label)         as the live server)       every 0.5 s)        split by clip)            (test results)
                                                                                              │
                                                    live server loads it and labels every dog ◄┘
```

The features are computed by `backend/features.py`, the same code the live server uses, so training and live data always match. Each row describes the last 2 seconds of one dog:

| Feature | Meaning |
|---|---|
| `speed_mean`, `speed_max`, `speed_std` | frame-to-frame speed in box heights per second |
| `net_speed` | start-to-end distance / time (ignores jitter) |
| `straightness` | net distance / path length (1 = straight line) |
| `horizontal_share` | how much of the movement is sideways |
| `aspect_mean`, `aspect_std` | box width / height (a lying dog is wider) |
| `height_change` | how fast the box grows (coming towards the camera) |
| `height_jitter` | relative variation of the box height |
| `fps` | samples per second |

Distances are divided by the dog's box height, so the numbers don't depend on how far away the dog is or on camera resolution.

## Steps

**1. Collect clips.** Cut 3–20 s clips with one behaviour each and sort them into one folder per label:

```
datasets/behaviour_clips/
    RESTING/   gate_lying_01.mp4  gate_sitting_02.mp4 ...
    WALKING/   ...
    RUNNING/   ...
```

Use at least 5 clips per label from different places and days. More clips help more than longer clips. Finer labels (`LYING`, `SITTING`, `STANDING`) also work. Their mapping to the dashboard's RESTING / WALKING / RUNNING is in `ACTIVITY_FOR_LABEL` in `backend/features.py`.

**2. Extract features** (from the repo root, with the venv active):

```bash
python -m training.behaviour.extract_features --clips datasets/behaviour_clips --out datasets/behaviour_features.csv
```

Options: `--step 0.5` (seconds between rows), `--window 2` (seconds of history), `--stride 2` (use every 2nd frame, faster), `--model models/<fine-tuned>.pt`. To add one clip later: `--video clip.mp4 --label RUNNING --append`.

**3. Train and evaluate:**

```bash
python -m training.behaviour.train_classifier --data datasets/behaviour_features.csv
```

It prints accuracy, macro F1, a per-class table, the confusion matrix, a comparison with the old speed-threshold rule and the most useful features. Put these in the report.

The test split is **by clip**: rows from the same clip are almost identical, so a random row split would give a fake, too-high score. With only one clip for a label it falls back to a row split and prints a warning.

**4. Use it.** The model is saved as `models/behaviour.joblib`, and the results as `models/behaviour.json`. Then either:

- restart the server, or
- click **Behaviour classifier** on the test page, or
- call `POST /api/models/behaviour/reload`.

The live view then shows the classifier's label and confidence for each dog. The checkbox turns it off again, back to the speed thresholds, so the two can be compared in the demo.

## Ideas for improving it

- **Pose features:** use a dog-pose model's keypoints (leg angles, head height) to tell lying, sitting and standing apart. Add them to `window_features` and to `FEATURE_NAMES` so the live server computes them too.
- **Other models:** try gradient boosting, or a small 1D-CNN/GRU on the raw box sequence. Anything with `predict_proba` and `classes_` can be saved in the same joblib format: `{"model", "features", "labels"}`.
- **Clean up labels:** go through the clips the model gets wrong (the confusion matrix shows which labels it mixes up).

Note: `.joblib` files are Python pickles, so they can run code when loaded. Only load models the team trained itself.
