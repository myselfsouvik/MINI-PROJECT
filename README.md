# 🐕 Street Dog Detection, Tracking & Behaviour Analysis

A computer-vision mini project that watches street dogs through any camera (laptop webcam, a phone over USB or Wi-Fi, a phone's own browser, or a video file). It uses **YOLO11** to find every dog, follows each one, works out whether it is resting, walking or running, raises alerts, and shows everything live in the browser. It also turns a public **animal-bite dataset** (7,029 dog-bite records) into charts.

**Status (28 Nov 2026):** the system works end to end; our own trained models are the next big step (see the checklist in [PLAN.md](PLAN.md#7-demo-checklist-definition-of-done)).

## Features

- **Any camera, several at once**: laptop webcam, phone over USB (DroidCam / Iriun), phone over Wi-Fi (IP Webcam), a phone's browser by scanning a QR code (no app), or an uploaded video.
- **Live detection and tracking**: a box and a number on every dog, a motion trail, dog and person counts.
- **Behaviour**: resting / walking / running from speed measured in dog-body-heights per second (works at any camera distance), smoothed so labels don't flicker. A trained classifier can replace the rule.
- **Alerts with photo and video clip**: a dog entering a zone you draw (e.g. a school gate), a dog running towards a person, 3+ dogs together.
- **Dog profiles**: every dog's photo, path on the camera picture, time spent per activity and its events.
- **Analytics**: activity split, heat map of where dogs spend time, speed chart.
- **Bites data insights**: charts by month, breed, body part, weekday, vaccination and rabies result.
- **Reports and export**: printable session report, CSV export of dogs, positions and events.
- **Demo-ready**: one command start, a backup demo video, a pre-demo laptop check, automatic clean-up of old data.
- **Tools for training our own models**: frame extraction with pre-filled boxes, detector evaluation (precision, recall, mAP, FPS), behaviour feature extraction and classifier training.

## Project structure

```
MINI-PROJECT/
├── backend/             # FastAPI server, cameras, inference, storage, classic console
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
├── frontend/            # React dashboard: pages, guided setup, presentation view
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
└── PLAN.md              # Roadmap and demo checklist
```

## How to run

### Quick start (a fresh clone, nothing installed)

1. **Install Python** 3.11 from https://www.python.org/downloads/ (on Windows, tick **"Add python.exe to PATH"**).
   On Windows you can skip this: `start.bat` offers to install it for you.
2. **Start DogWatch:**
   - Windows: double-click **`start.bat`** in the project folder.
   - macOS / Linux: run `./start.sh` in a terminal.
3. The browser opens **http://127.0.0.1:8000** and a guided setup starts. No dog nearby? Pick **Demo video**.

The first start installs everything into a private `.venv` folder (about 1 GB, 5 to 15 minutes, needs internet once).
Later starts take a few seconds and work offline. To stop it, close the window (or press Ctrl+C).

That's all: no Node.js, database or other setup. The dashboard comes ready-built in `frontend/dist`, the detector
model is in `models/`, and the data is stored in a local SQLite file. Nothing is deployed or sent anywhere.

```bash
start.bat --demo                  # also play the backup demo video (3 dogs, a demo zone) straight away
start.bat --source 1              # also watch webcam / USB phone number 1
./start.sh --demo                 # macOS / Linux
python -m backend.doctor          # (inside .venv) checks Python, packages, model speed, ports, Wi-Fi; says what to fix
```

Phones on the same Wi-Fi can join as cameras by scanning the QR code on the **Cameras** page.

**If something goes wrong:** delete the `.venv` folder and start again. If the install fails on a very new Python
(3.13 or later), install Python 3.11 and delete `.venv`. On Ubuntu/Debian, `sudo apt install python3-venv` first.

### Manual setup (for development)

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
source .venv/bin/activate         # macOS / Linux
pip install -r requirements.txt
```

Working on the dashboard needs Node.js: see [frontend/README.md](frontend/README.md). After changing `frontend/`,
run `npm run build` and commit `frontend/dist` too, so everyone else gets the change without Node.js.

### Backend server

```bash
python -m backend.server --source 0        # or 1 for a USB phone, or a video file
python -m backend.server --phone           # phones connect from their browser by scanning a QR code
```

Open http://127.0.0.1:8000 for the dashboard. The first time, a guided setup walks you through adding a camera, checking a dog is seen and marking a zone. Pages: **Overview** (what is happening now), **Live** (one camera big, zones, recording), **Alerts**, **Dogs** (profiles), **Activity** (charts and session reports), **Bites data**, **Cameras**, **Settings** and **Help**, plus a **Presentation view** for showing it to a class. API docs are at http://127.0.0.1:8000/docs. Details: [frontend/README.md](frontend/README.md) and [backend/README.md](backend/README.md).

The older one-page console is still at http://127.0.0.1:8000/console.

### Original prototype scripts

The scripts in `legacy/` find the model and data files themselves, so you can run them from any folder.

| Command | What happens |
|---|---|
| `python legacy/detect.py` | Opens the camera, boxes any dog (confidence ≥ 60%), saves a crop to `legacy/dog_images/` every 3 seconds |
| `python legacy/dogid.py` | Same, but tracks each dog and saves `dog_ID_<id>_<n>.jpg` every 2 seconds per dog |
| `python legacy/dog_behaviour.py` | Shows ID, speed and activity level on screen and appends rows to `legacy/dog_features.csv` |
| `python legacy/preprocessing.py` | Cleans the bites dataset and writes `data/tabular/cleaned_animal_bites_dogs.csv` |

Press **Q** in the camera window to stop.

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

1. **Camera**: each camera runs in its own thread and always hands over the newest frame, so a slow laptop skips frames instead of falling behind.
2. **Detection and tracking**: YOLO11-nano finds dogs (and people, for alerts); ByteTrack keeps the same number on a dog from frame to frame.
3. **Speed**: how far the centre of the box moved, divided by the box height and the time between frames, gives **dog-body-heights per second**, averaged over about a second.
4. **Activity**: under 0.25 is resting, under 1.5 is walking, anything faster is running. If a trained behaviour classifier is in `models/`, it is used instead.
5. **Alerts**: zone, running towards a person, and pack rules run on every frame; each alert saves a photo and a short clip.
6. **Storage**: dogs, one position per dog per second, and events go into SQLite; the dashboard reads them through the API and a live WebSocket.

The original prototype scripts in `legacy/` work the old way (pixels per second, LOW / NORMAL / HIGH) and are kept for reference.

## Dataset

`Health_AnimalBites.csv` is a public animal-bite records dataset from Louisville, Kentucky (bite date, species, breed, gender, colour, vaccination, body part bitten, quarantine, rabies result), with 7,029 dog-bite records from 2010–2017. The **Bites data** page charts them. Only 59 of those records have a rabies test result (58 negative, 1 positive), which is too imbalanced to train a classifier on.

## Limitations

- The detector is the stock pre-trained model; it has not been fine-tuned on our own street footage yet.
- The behaviour classifier is built but not trained yet, so activity comes from speed.
- A dog that leaves the picture and comes back gets a new number.
- The rabies data has 1 positive case out of 59, so it can't train a classifier; the Insights charts use all 7,029 dog-bite records instead.

## Next steps

- Record and label our own footage, fine-tune the detector and train the behaviour classifier, with before/after metrics.
- Recognise the same dog across days, the base for a street-dog census.

## Team

- Souvik Banerjee ([@myselfsouvik](https://github.com/myselfsouvik))
- Jagrit Mondal ([@Jagrit-Dev](https://github.com/Jagrit-Dev))
- Samaraho
- Nandini
- Shalmali
