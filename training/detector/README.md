# detector

Fine-tuning the YOLO dog detector (PLAN 3.1).

The steps below go from our own camera recordings to a better model shown in the dashboard.

## 1. Collect footage

Open the dashboard, connect a phone or webcam pointed at a street, and press **● Record**. Videos are saved in `recordings/captures/`. Uploaded videos in `recordings/uploads/` work too. Try to cover:
- different times of day
- near and far dogs
- groups of dogs
- partly hidden dogs
- streets with cats, goats or cows (hard negatives)

## 2. Turn videos into frames, pre-labelled

```bash
python -m training.detector.extract_frames recordings/captures --out datasets/street_dogs/unlabelled
```

- Keeps one **full frame** per second (`--every 2` keeps one every 2 s).
- Skips near-identical frames.
- Keeps about 30% of the frames with no dog, as hard negatives (`--negatives`).
- Writes YOLO boxes from the current model, so labellers only fix mistakes instead of drawing every box.

## 3. Label

1. Import `datasets/street_dogs/unlabelled` into CVAT, Label Studio or Roboflow as a **YOLO 1.1** dataset (`images/`, `labels/`, `classes.txt`).
2. Fix the boxes:
   - delete wrong boxes
   - add missed dogs
   - make boxes tight
3. Export the dataset back to YOLO format.
4. Split it into train, val and test (Roboflow can do this). Put about 300 frames in **test**. Never train on them, and use footage from different days than train where possible.

Add public data to **train only**, for example Roboflow Universe street-dog sets or Open Images "Dog".

## 4. Measure the baseline (before training)

```bash
python -m training.detector.evaluate --data training/detector/data.yaml --split test \
    --models models/yolo11n.pt --save-errors runs/errors --table runs/baseline.md
```

| Output | Meaning |
|---|---|
| mAP50, mAP50-95 | overall detection quality (higher is better) |
| precision | of the dogs we report, how many are real |
| recall | of the real dogs, how many we find |
| F1 | balance of the two; precision, recall and F1 are measured at confidence 0.5, the same as the app |
| false alarms / empty image | dogs "seen" in frames with no dog |
| FPS | speed on this laptop |

- The results are also saved to `models/yolo11n.json`, which the dashboard shows under **Model**.
- `runs/errors/` has a picture of every mistake for the report: green = correct, red = false alarm, yellow = missed dog.

## 5. Train on Colab or Kaggle (free GPU)

```python
!pip install ultralytics
from ultralytics import YOLO
model = YOLO("yolo11n.pt")          # also try yolo11s.pt
model.train(data="/content/street_dogs/data.yaml", epochs=100, imgsz=640, batch=16, patience=20)
```

- Change `path:` in `data.yaml` to where the dataset is on Colab.
- Download `runs/detect/train/weights/best.pt` and rename it, for example to `models/dogs_v1.pt`.
- Keep the full `runs/` folder on Google Drive, not in git.

## 6. Compare on the same test set

```bash
python -m training.detector.evaluate --data training/detector/data.yaml \
    --models models/yolo11n.pt models/dogs_v1.pt --table runs/comparison.md
```

- Paste `runs/comparison.md` into the report.
- Pick the model in the dashboard, under **Model**. The app finds the dog class by name, so a dog-only model and the COCO model both work.

## 7. Faster model for the demo laptop (optional)

```bash
pip install onnx onnxruntime
yolo export model=models/dogs_v1.pt format=onnx imgsz=640
```

Copy the `.onnx` file into `models/` and run `evaluate.py` on it to check that the FPS improved without losing accuracy.
