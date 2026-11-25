# Using a phone as the camera

Every option below ends with a **source** you can give the app: a webcam number (`1`) or a URL. Check it first with the camera test:

```bash
python -m backend.camera_test --list              # see which webcam numbers exist
python -m backend.camera_test --source 1 --detect # try one, with dog detection
```

| Option | Cable? | Best for | Source you get |
|---|---|---|---|
| A. DroidCam / Iriun over **USB (Type-C)** | Yes | The demo: steady and no lag | Webcam number, e.g. `1` |
| B. IP Webcam / DroidCam over **Wi-Fi** | No | Walking around, phone on a stand | URL, e.g. `http://192.168.1.5:8080/video` |
| C. Phone **browser** (QR code) | No | No app to install | Coming in a later checkpoint |

> **Why not Bluetooth?** Bluetooth carries roughly 1–2 Mbps, not enough for live video, and there's no standard Bluetooth webcam mode. USB and Wi-Fi do the job properly.

---

## A. Phone over USB cable (recommended for the demo)

Uses **DroidCam** (Android + iPhone) or **Iriun Webcam** (Android + iPhone). Both have a phone app and a Windows client; the free versions are enough.

1. Install the app on the phone and the matching **PC client** on the laptop (from the app's official website).
2. **Android:** turn on *Developer options → USB debugging* (tap *Build number* 7 times in *Settings → About phone* to unlock Developer options). Allow the laptop when the phone asks.
   **iPhone:** the PC client needs Apple's drivers, so install iTunes / Apple Devices on Windows. Tap *Trust* on the phone.
3. Plug in the Type-C cable, open the app on the phone, then in the PC client choose **USB** and connect.
4. The phone is now a normal webcam. Find its number:
   ```bash
   python -m backend.camera_test --list
   ```
   It's usually the highest number (laptop webcam is `0`, phone is `1`).
5. Test it: `python -m backend.camera_test --source 1 --detect`

## B. Phone over Wi-Fi

1. Connect the phone and the laptop to the **same Wi-Fi**. College Wi-Fi often blocks device-to-device traffic. If it does, turn on the **phone's hotspot** and connect the laptop to it.
2. Install **IP Webcam** (Android) or **DroidCam** (Android / iPhone) and start the camera in the app.
3. The app shows an address like `http://192.168.1.5:8080`. Open it in the laptop's browser to make sure it works.
4. Test it:
   ```bash
   python -m backend.camera_test --phone 192.168.1.5                 # IP Webcam (port 8080)
   python -m backend.camera_test --phone 192.168.1.5 --app droidcam  # DroidCam (port 4747)
   # or give the full URL yourself
   python -m backend.camera_test --source http://192.168.1.5:8080/video
   ```

## Troubleshooting

| Problem | Fix |
|---|---|
| `Could not open webcam 1` | Make sure the DroidCam/Iriun PC client is running and connected. Close other apps using the camera (Zoom, Meet, Camera app). |
| `--list` doesn't show the phone | Reconnect in the PC client; try another cable (some are charge-only); re-allow USB debugging. |
| `Could not open stream …` | Open the URL in a browser first. Check both devices are on the same network; switch to the phone hotspot. |
| Video is laggy over Wi-Fi | Lower the resolution in the phone app (640×480 is plenty for detection), or use USB. |
| Phone screen turns off and stream stops | Keep the app in the foreground and disable screen timeout / battery saver. |
