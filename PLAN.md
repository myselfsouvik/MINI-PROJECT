# Project Plan: Street Dog Monitoring System v2

**Team:** Souvik · Jagrit · Samaraho · Nandini · Shalmali
**Goal:** Turn the current set of camera scripts into a complete, demo-ready ML system: a **live web dashboard** that takes any camera (laptop, phone over Wi-Fi, or phone over USB), runs a **model we fine-tuned ourselves**, and shows dogs, their behaviour and alerts in real time.

**Ground rule:** this is an ML project, so **no external LLM / AI APIs**. Every model runs locally and is trained or fine-tuned by us. Labelling tools (CVAT, Label Studio, Roboflow annotator) are fine because they don't make predictions for us.

---

## 1. Where we are now

*Updated 28 Nov 2026.* The system works end to end: a FastAPI server takes a laptop webcam, a phone over USB or Wi-Fi, a phone's browser via QR code, or a video file; detects and tracks dogs; labels resting / walking / running from normalised speed; raises zone, running-at-person and pack alerts with photo and clip; stores everything in SQLite; and shows it in a React dashboard (Overview, Live, Alerts, Dogs, Activity, Bites data, Cameras, Settings, Help) with a guided first-run setup and a presentation view for the pitch. The older one-page console stays at `/console`. 147 Python and 18 frontend tests pass.

Still to do: our own trained models (the detector still uses the **stock YOLO11n**, and the behaviour classifier has its scripts but no labelled clips), the dog pose model, and recognising the same dog across days. The tools for collecting frames, labelling and evaluating are in `training/`.

---

## 2. What we're building

### 2.1 Architecture

```
 Camera sources                     Backend (Python, FastAPI)                 Frontend (browser)
 ───────────────                    ─────────────────────────                ───────────────────
 Laptop webcam (index 0) ─┐
 Phone via USB (DroidCam) ┼──► CameraManager ──► Inference worker ──► SQLite DB ──► REST API ──► Dashboard
 Phone via Wi-Fi (IP URL) ┤      (OpenCV)        • YOLO detect+track   (dogs,        WebSocket   • Live view
 Phone browser (WebRTC/WS)┤                      • Pose / behaviour     events,      (live       • Dog gallery
 Video file (.mp4)  ──────┘                      • Alerts / zones       alerts)       frames)    • Analytics
                                                                       + snapshots               • Alerts
```

### 2.2 Connecting cameras (phones included)

| Method | How | Works on | Notes |
|---|---|---|---|
| **Laptop webcam** | `cv2.VideoCapture(0)` | All | Already works |
| **Phone over USB (Type-C)** ✅ recommended for demo | **DroidCam** or **Iriun Webcam** app on phone + PC client → phone appears as a normal webcam (`VideoCapture(1)`) | Android & iPhone, Windows | Most stable: no Wi-Fi lag. Android: enable USB debugging. |
| **Phone over Wi-Fi** | **IP Webcam** (Android) / DroidCam → gives a URL like `http://192.168.x.x:8080/video` → `cv2.VideoCapture(url)` | Android, iPhone | Phone and laptop must be on the same Wi-Fi (a phone hotspot works) |
| **Phone browser, no app** ⭐ cool demo | Phone opens `https://<laptop-ip>:8000/phone`, page uses the camera (`getUserMedia`) and streams frames to the backend over WebSocket | Any phone | Needs HTTPS: use a self-signed cert (`mkcert`). Scan a QR code shown on the dashboard to connect. |
| **Windows 11 Phone Link** | "Connected camera" feature makes an Android phone a webcam | Android, Win 11 | Backup option |
| **Video file** | `VideoCapture("clip.mp4")` | All | Needed for repeatable testing and for when no dog is around during the demo |
| ~~Bluetooth camera~~ | ❌ Not planned | — | Bluetooth bandwidth (~1–2 Mbps) is too low for live video and there's no standard Bluetooth webcam profile. USB/Wi-Fi do the same job better. |

The dashboard gets a **source picker**: dropdown of detected webcams + "Add IP camera URL" + "Connect phone (QR)" + "Upload video".

### 2.3 Dashboard pages

1. **Live**: video with boxes, IDs, motion trails, activity labels; FPS, dog count; confidence slider; overlay toggles.
2. **Dogs**: gallery of every tracked dog (best crop, first/last seen, time spent per activity).
3. **Analytics**: charts of activity over time, speed distribution, heat-map of where dogs spend time.
4. **Alerts**: log of events (dog entered a zone, dog running toward a person, crowd of 3+ dogs) with snapshot.
5. **Zones**: draw a polygon on the camera view (e.g. "school gate") to watch.
6. **Model**: shows which model is loaded and its test metrics (stock vs. our fine-tuned one). Very useful for viva.
7. **Insights**: charts from the animal-bites dataset (bites by breed, month, vaccination status).

**Tech:** FastAPI + Uvicorn (backend), React + Vite + Chart.js (frontend), SQLite (storage). If React is too much for the time we have, a fallback is plain HTML/JS served by FastAPI. Everything runs on one laptop, offline.

---

## 3. Making the AI more accurate (the ML core)

### 3.1 Fine-tune the dog detector
1. **Baseline first.** Collect and label a **test set of ~300 of our own street-dog frames** (different times of day, distances, groups, partial views). Measure the stock `yolo11n.pt` on it: **precision, recall, mAP50, mAP50-95, FPS**.
2. **Build a training set (~2,000–4,000 images):**
   - our own footage (campus, local streets): save **full frames**, not just crops
   - public datasets: Roboflow Universe street-dog sets, Open Images V7 "Dog" class, Stanford Dogs (has boxes)
   - **hard negatives**: cats, goats, cows, calves and bags, which get confused with dogs on Indian streets
3. **Label** in CVAT / Label Studio / Roboflow. Speed it up by auto-labelling with the current model, then correcting by hand.
4. **Train** `yolo11n` and `yolo11s` on Google Colab / Kaggle (free GPU), ~100 epochs, image size 640, default augmentation. Keep the class list `dog` (+ `person` for alerts).
5. **Compare** baseline vs fine-tuned on the *same* test set → table + confusion examples for the report.
6. **Export** the best model to ONNX/OpenVINO for faster CPU inference on the demo laptop.

### 3.2 Better behaviour recognition
- **Fix the speed measure**: divide pixel speed by box height → *body-lengths per second*, so it doesn't depend on distance or resolution. Smooth over the last ~1 s to stop the label flickering.
- **Dog pose model**: fine-tune `yolo11n-pose` on the Ultralytics **Dog-Pose** dataset (24 keypoints).
- **Behaviour classifier (our own trained model)**: label ~2-second clips from our footage as **lying / sitting / standing / walking / running**. Features = keypoint angles + normalised speed over the window. Train **Random Forest / XGBoost** (scikit-learn), and optionally a small LSTM. Report accuracy, F1 and a confusion matrix.
- **Alerts (rule-based on top of the models)**: dog running toward a detected person, dog inside a zone, 3+ dogs grouped. We don't claim "aggression detection" without data to prove it.

### 3.3 Stretch: recognise the same dog across days
Extract an embedding for each crop (pretrained ResNet/MobileNet, then fine-tune with triplet loss on our own crops). Match by cosine similarity → stable IDs between sessions. Only if time allows.

### 3.4 The bites dataset
Drop the rabies classifier (1 positive case can't train anything). Instead do a proper **EDA notebook** on the 7,029 dog records (breed, season, vaccination, body part, outcome) feeding the **Insights** page. Optionally train a classifier on a balanced target such as outcome/disposition.

---

## 4. Who does what (proposal, so discuss and swap freely)

| Person | Area | Deliverables |
|---|---|---|
| **Jagrit** | Backend + camera integration | FastAPI server, CameraManager (webcam, USB phone, IP URL, browser-phone over WebSocket, video file), inference worker, SQLite schema, live stream to frontend, repo setup (`requirements.txt`, `.gitignore`, folder structure) |
| **Nandini** | Frontend dashboard | React app: Live, Dogs, Analytics, Alerts, Zones, Model, Insights pages; source picker + QR connect; charts |
| **Souvik** | Detector fine-tuning | Baseline evaluation, training runs on Colab, model comparison table, ONNX/OpenVINO export |
| **Shalmali** | Data collection + labelling + evaluation | Record street-dog footage, build train/test sets, label in CVAT/Roboflow, hard-negative images, dataset documentation |
| **Samaraho** | Behaviour ML + bites EDA | Normalised speed + smoothing, dog-pose fine-tune, behaviour classifier, alert rules, bites EDA notebook |

Everyone: write their own section of the final report and prepare their part of the demo.

---

## 5. Timeline (6 weeks, adjust to our submission date)

| Week | Milestone |
|---|---|
| **1** | Repo restructure, `requirements.txt`. Phone camera working via USB + Wi-Fi in a test script. Start recording footage. Dashboard skeleton. Test set labelled. |
| **2** | Backend streams live annotated video to dashboard. Baseline metrics measured. Training set ~50% labelled. Normalised speed done. |
| **3** | First fine-tuned detector. Dogs + Alerts pages working with DB. Pose model fine-tuned. |
| **4** | Browser-phone (QR) camera. Behaviour clips labelled, classifier trained. Analytics + Zones pages. |
| **5** | Swap in best models, integrate the behaviour classifier into the live pipeline. Insights page. End-to-end testing with recorded videos. |
| **6** | Bug fixes, performance tuning, final report, slides, demo rehearsal (with a backup video in case no dog shows up). |

---

## 6. Proposed folder structure

```
MINI-PROJECT/
├── backend/            # FastAPI app, camera manager, inference, DB
├── frontend/           # React dashboard
├── training/
│   ├── detector/       # data.yaml, train/eval scripts, results
│   ├── pose/
│   └── behaviour/      # feature extraction + classifier notebooks
├── notebooks/          # bites dataset EDA
├── legacy/             # current detect.py, dogid.py, dog_behaviour.py, preprocessing.py
├── models/             # final weights only (large datasets stay on Google Drive)
├── requirements.txt
└── README.md
```

## 7. How we work

- One branch per feature (`feature/phone-camera`, `feature/dashboard-live`, …). Merge to `main` through pull requests, reviewed by one other person.
- **Don't commit datasets, training runs or videos.** Keep them in a shared Google Drive folder and link it in the README.
- Owner (Souvik) adds Samaraho, Nandini and Shalmali as GitHub collaborators.
- Short sync twice a week. Update the checklist below.

## 8. Demo checklist (definition of done)

*Status on 28 Nov 2026.*

- [x] Dashboard opens with one command (`start.bat`)
- [x] Dashboard app with one page per job, a guided first-run setup and a presentation view
- [x] Laptop webcam, phone over USB and phone over Wi-Fi/QR all work as sources
- [ ] Fine-tuned detector shows a measurable improvement over the stock model on our own test set (evaluation tools ready, needs labelled footage)
- [ ] Behaviour classifier with reported accuracy / F1 / confusion matrix (training scripts ready, needs labelled clips)
- [x] At least 2 working alert types with snapshots (3 types, with photo and clip)
- [x] Analytics and Insights pages show real charts
- [x] Backup demo video ready (`start.bat --demo`)
- [ ] Final report + slides with metrics tables
