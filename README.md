# 🐕 Street Dog Detection, Tracking & Behaviour Analysis

A computer-vision mini project that uses a webcam and **YOLO11** to detect dogs in real time, give each dog a tracking ID, measure how it moves, and log the data for analysis. It also includes a cleaned public-health **animal-bite dataset** for studying dog bites and rabies results.

## Features

- **Live dog detection**: draws a box around every dog the camera sees and saves a cropped photo.
- **Per-dog tracking**: each dog gets an ID (`Dog ID: 3`) and its photos are saved separately.
- **Behaviour analysis**: calculates movement speed and labels each dog's activity as **LOW**, **NORMAL** or **HIGH**.
- **Data logging**: writes timestamped position, speed and activity data to `dog_features.csv`.
- **Dataset preprocessing**: filters the animal-bites dataset down to dog records with a known rabies test result.

## Project structure

```
MINI-PROJECT/
├── detect.py            # Detect dogs and save cropped images
├── dogid.py             # Detect + track dogs, save images per dog ID
├── dog_behaviour.py     # Track movement, speed and activity, log to CSV
├── preprocessing.py     # Clean the animal-bites dataset
├── yolo11n.pt           # Pre-trained YOLO11-nano weights (COCO)
├── dog_features.csv     # Sample output from dog_behaviour.py
├── dog_images/          # Sample cropped dog images
└── data/tabular/
    ├── Health_AnimalBites.csv           # Raw dataset (9,003 records)
    └── cleaned_animal_bites_dogs.csv    # Output of preprocessing.py
```

## Requirements

- Python 3.9+
- A webcam (for the three camera scripts)

```bash
pip install ultralytics opencv-python pandas scikit-learn
```

## How to run

Run every command from the project folder so the scripts can find `yolo11n.pt` and the data files.

| Command | What happens |
|---|---|
| `python detect.py` | Opens the camera, boxes any dog (confidence ≥ 60%), saves a crop to `dog_images/` every 3 seconds |
| `python dogid.py` | Same, but tracks each dog and saves `dog_ID_<id>_<n>.jpg` every 2 seconds per dog |
| `python dog_behaviour.py` | Shows ID, speed and activity level on screen and appends rows to `dog_features.csv` |
| `python preprocessing.py` | Cleans the bites dataset and writes `data/tabular/cleaned_animal_bites_dogs.csv` |

Press **Q** in the camera window to stop.

## How it works

1. **Detection**: each frame goes through YOLO11-nano. Only COCO class 16 (*dog*) with confidence ≥ 0.60 is kept.
2. **Tracking**: `model.track(persist=True)` uses YOLO's built-in tracker to keep the same ID on a dog between frames.
3. **Movement**: the centre of each dog's box is compared with its previous position:
   `speed = distance moved (px) / time between frames (s)`
4. **Activity level**:

   | Speed (px/s) | Activity |
   |---|---|
   | < 20 | LOW |
   | 20 – 80 | NORMAL |
   | > 80 | HIGH |

### `dog_features.csv` columns

`timestamp, dog_id, center_x, center_y, movement_pixels, speed_pixels_per_second, activity_level, confidence`

## Dataset

`Health_AnimalBites.csv` is a public animal-bite records dataset (bite date, species, breed, gender, colour, vaccination, body part bitten, quarantine, rabies result). After keeping only dogs with a POSITIVE/NEGATIVE rabies result, **59 records** remain (58 negative, 1 positive), which is too imbalanced to train a classifier on.

## Limitations

- Uses the stock pre-trained model; it has not been fine-tuned on street-dog images.
- Tracking IDs reset every run, and a dog that leaves and re-enters the frame may get a new ID.
- Speed is in pixels per second, so thresholds depend on camera distance and resolution.

## Future work

- Single `main.py` entry point that also works with video files.
- Dashboard (e.g. Streamlit) with live feed, charts and dog gallery.
- Alerts for aggressive or fast-approaching dogs, and zone-based monitoring.
- Re-identifying the same dog across sessions.
- Exploratory analysis of the bite dataset (breed, season, vaccination).

## Team

- Souvik Banerjee ([@myselfsouvik](https://github.com/myselfsouvik))
- Jagrit Mondal ([@Jagrit-Dev](https://github.com/Jagrit-Dev))
- Samaraho
- Nandini
- Shalmali
