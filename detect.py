from ultralytics import YOLO
import cv2
import os
from datetime import datetime
import time


# Load YOLO model
model = YOLO("yolo11n.pt")

# Folder where ONLY dog pictures will be saved
save_folder = "dog_images"
os.makedirs(save_folder, exist_ok=True)

# Open camera
cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("ERROR: Camera could not be opened.")
    exit()

print("Dog Detection Started")
print("Only dog images will be saved.")
print("Press Q to quit.")

# Prevent saving the same dog continuously
last_saved_time = 0
save_delay = 3   # seconds

while True:

    ret, frame = cap.read()

    if not ret:
        print("ERROR: Could not read camera.")
        break

    # YOLO detection
    results = model(frame, verbose=False)

    for result in results:

        for box in result.boxes:

            class_id = int(box.cls[0])
            confidence = float(box.conf[0])

            # COCO class 16 = DOG
            if class_id == 16 and confidence >= 0.60:

                # Dog bounding box
                x1, y1, x2, y2 = map(int, box.xyxy[0])

                # Make sure coordinates are inside image
                x1 = max(0, x1)
                y1 = max(0, y1)
                x2 = min(frame.shape[1], x2)
                y2 = min(frame.shape[0], y2)

                # Draw dog box on camera screen
                cv2.rectangle(
                    frame,
                    (x1, y1),
                    (x2, y2),
                    (0, 255, 0),
                    2
                )

                cv2.putText(
                    frame,
                    f"Dog {confidence:.2f}",
                    (x1, y1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 255, 0),
                    2
                )

                # Save only once every 3 seconds
                current_time = time.time()

                if current_time - last_saved_time >= save_delay:

                    # CROP ONLY THE DOG
                    dog_image = frame[y1:y2, x1:x2]

                    # Make sure crop is valid
                    if dog_image.size > 0:

                        filename = datetime.now().strftime(
                            "dog_%Y%m%d_%H%M%S.jpg"
                        )

                        filepath = os.path.join(
                            save_folder,
                            filename
                        )

                        # Save ONLY dog crop
                        cv2.imwrite(filepath, dog_image)

                        print("Dog saved:", filepath)

                        last_saved_time = current_time

    # Show camera
    cv2.imshow("Dog Detection", frame)

    # Press Q to quit
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

# Close everything
cap.release()
cv2.destroyAllWindows()

print("Dog Detection Stopped.")

