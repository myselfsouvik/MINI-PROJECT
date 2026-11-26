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
├── backend/             # (in progress) FastAPI server, cameras, inference
│   ├── server.py        # start the web server: python -m backend.server
│   ├── app.py           # API routes, live video stream, WebSocket
│   ├── pipeline.py      # detection + tracking + behaviour per camera
│   ├── behaviour.py     # speed and RESTING / WALKING / RUNNING labels
│   ├── alerts.py        # zone, running-at-person and pack alerts
│   ├── features.py      # movement features + trained behaviour classifier
│   ├── demo.py          # backup demo video (python -m backend.demo)
│   ├── doctor.py        # pre-demo laptop check (python -m backend.doctor)
│   ├── db.py            # SQLite storage
│   ├── cameras.py       # CameraSource: webcam / USB phone / Wi-Fi phone / video file
│   └── camera_test.py   # command-line camera checker
├── docs/PHONE_CAMERA.md # how to connect a phone as the camera
├── tests/               # automated tests (python -m pytest tests)
├── frontend/            # (in progress) React dashboard
├── training/            # detector/: recordings → pre-labelled frames → evaluation table; behaviour/: clips → features → classifier
├── notebooks/           # (in progress) bites dataset EDA
├── models/
│   └── yolo11n.pt       # Pre-trained YOLO11-nano weights (COCO)
├── legacy/              # Original prototype scripts
│   ├── detect.py        # Detect dogs and save cropped images
│   ├── dogid.py         # Detect + track dogs, save images per dog ID
│   ├── dog_behaviour.py # Track movement, speed and activity, log to CSV
│   ├── preprocessing.py # Clean the animal-bites dataset
│   ├── dog_features.csv # Sample output from dog_behaviour.py
│   └── dog_images/      # Sample cropped dog images
├── data/tabular/
│   ├── Health_AnimalBites.csv           # Raw dataset (9,003 records)
│   └── cleaned_animal_bites_dogs.csv    # Output of preprocessing.py
├── start.bat / start.sh # one-command start (dashboard + phone QR)
├── requirements.txt
└── PLAN.md              # Roadmap and who does what
```

## Setup

- Python 3.10 – 3.12 (recommended; 3.11 is what we test with)
- A webcam, or a phone used as a webcam (see PLAN.md)

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

## How to run

The scripts find the model and data files themselves, so you can run them from any folder.

| Command | What happens |
|---|---|
| `python legacy/detect.py` | Opens the camera, boxes any dog (confidence ≥ 60%), saves a crop to `legacy/dog_images/` every 3 seconds |
| `python legacy/dogid.py` | Same, but tracks each dog and saves `dog_ID_<id>_<n>.jpg` every 2 seconds per dog |
| `python legacy/dog_behaviour.py` | Shows ID, speed and activity level on screen and appends rows to `legacy/dog_features.csv` |
| `python legacy/preprocessing.py` | Cleans the bites dataset and writes `data/tabular/cleaned_animal_bites_dogs.csv` |

Press **Q** in the camera window to stop.

### Demo day: one command

```bash
python -m backend.doctor          # checks Python, packages, model speed, ports, Wi-Fi; says what to fix
start.bat                         # Windows: double-click. Opens the dashboard, phones can scan the QR code
start.bat --demo                  # same + backup demo video (3 dogs, demo zone) if no dog shows up
./start.sh --demo                 # macOS / Linux
```

### Backend server (new)

```bash
python -m backend.server --source 0        # or 1 for a USB phone, or a video file
python -m backend.server --phone           # phones connect from their browser by scanning a QR code
```

Open http://127.0.0.1:8000 for live video with dog boxes, activity labels, saved dogs, events and alerts (draw a zone like a school gate on the video and get an alert with a photo when a dog walks in), analytics (heat map, speeds), video upload, a model picker, a **Record** button for collecting training clips and a short video clip with every alert, insights from the animal-bites dataset, and http://127.0.0.1:8000/docs for the API. Details: [backend/README.md](backend/README.md).

### Testing a camera (laptop, phone over USB or Wi-Fi)

```bash
python -m backend.camera_test --list                  # which webcams exist (a USB phone shows up here)
python -m backend.camera_test --source 1 --detect     # phone over USB with dog detection
python -m backend.camera_test --phone 192.168.1.5     # phone over Wi-Fi (IP Webcam app)
python -m backend.camera_test --source clip.mp4       # recorded video
```

Setting up the phone: see [docs/PHONE_CAMERA.md](docs/PHONE_CAMERA.md).

### Running the tests

```bash
python -m pytest tests -q
```

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
- Re-identifying the same dog across sessions.
- Exploratory analysis of the bite dataset (breed, season, vaccination).

## Team

- Souvik Banerjee ([@myselfsouvik](https://github.com/myselfsouvik))
- Jagrit Mondal ([@Jagrit-Dev](https://github.com/Jagrit-Dev))
- Samaraho
- Nandini
- Shalmali
