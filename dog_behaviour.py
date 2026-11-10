from ultralytics import YOLO
import cv2
import math
import time
import csv
import os

# ==========================================
# 1. LOAD YOLO MODEL
# ==========================================

model = YOLO("yolo11n.pt")


# ==========================================
# 2. OPEN CAMERA
# ==========================================

cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("ERROR: Camera could not be opened.")
    exit()

print("Dog Movement + Activity Analysis Started")
print("Press Q to quit.")


# ==========================================
# 3. DATA STORAGE
# ==========================================

# Previous position of each dog
previous_positions = {}

# Movement accumulated for each dog
movement_history = {}

# Time when each dog was first detected
start_time = {}


# ==========================================
# 4. CSV FILE
# ==========================================

csv_file = "dog_features.csv"

file_exists = os.path.exists(csv_file)

csv_output = open(
    csv_file,
    "a",
    newline=""
)

csv_writer = csv.writer(csv_output)

if not file_exists:

    csv_writer.writerow([
        "timestamp",
        "dog_id",
        "center_x",
        "center_y",
        "movement_pixels",
        "speed_pixels_per_second",
        "activity_level",
        "confidence"
    ])


# ==========================================
# 5. MAIN LOOP
# ==========================================

while True:

    ret, frame = cap.read()

    if not ret:

        print("ERROR: Could not read camera.")
        break


    current_time = time.time()


    # ======================================
    # YOLO TRACKING
    # ======================================

    results = model.track(
        frame,
        persist=True,
        classes=[16],       # 16 = dog
        verbose=False
    )


    # ======================================
    # PROCESS EACH RESULT
    # ======================================

    for result in results:

        if result.boxes is None:
            continue


        # ==================================
        # PROCESS EACH DOG
        # ==================================

        for box in result.boxes:


            # -------------------------------
            # Confidence
            # -------------------------------

            confidence = float(box.conf[0])


            if confidence < 0.60:
                continue


            # -------------------------------
            # Dog Tracking ID
            # -------------------------------

            if box.id is None:
                continue

            dog_id = int(box.id[0])


            # -------------------------------
            # Bounding Box
            # -------------------------------

            x1, y1, x2, y2 = map(
                int,
                box.xyxy[0]
            )


            # -------------------------------
            # Dog Center
            # -------------------------------

            center_x = int(
                (x1 + x2) / 2
            )

            center_y = int(
                (y1 + y2) / 2
            )


            # ==================================
            # MOVEMENT CALCULATION
            # ==================================

            movement = 0
            speed = 0


            if dog_id in previous_positions:

                old_x, old_y, old_time = \
                    previous_positions[dog_id]


                # Difference in position

                dx = center_x - old_x
                dy = center_y - old_y


                # Distance moved

                movement = math.sqrt(
                    dx ** 2 + dy ** 2
                )


                # Time difference

                time_difference = (
                    current_time - old_time
                )


                # Speed

                if time_difference > 0:

                    speed = (
                        movement /
                        time_difference
                    )


            # Save current position

            previous_positions[dog_id] = (
                center_x,
                center_y,
                current_time
            )


            # ==================================
            # MOVEMENT HISTORY
            # ==================================

            if dog_id not in movement_history:

                movement_history[dog_id] = 0

            movement_history[dog_id] += movement


            # ==================================
            # ACTIVITY LEVEL
            # ==================================

            if speed < 20:

                activity_level = "LOW"

            elif speed < 80:

                activity_level = "NORMAL"

            else:

                activity_level = "HIGH"


            # ==================================
            # DRAW DOG BOX
            # ==================================

            cv2.rectangle(
                frame,
                (x1, y1),
                (x2, y2),
                (0, 255, 0),
                2
            )


            # ==================================
            # DISPLAY DOG INFORMATION
            # ==================================

            label1 = (
                f"Dog ID: {dog_id}"
            )

            label2 = (
                f"Speed: {speed:.1f}"
            )

            label3 = (
                f"Activity: {activity_level}"
            )


            # ID

            cv2.putText(
                frame,
                label1,
                (x1, y1 - 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 0),
                2
            )


            # Speed

            cv2.putText(
                frame,
                label2,
                (x1, y1 - 20),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 0),
                2
            )


            # Activity

            cv2.putText(
                frame,
                label3,
                (x1, y2 + 25),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 0),
                2
            )


            # ==================================
            # SAVE FEATURES
            # ==================================

            timestamp = time.strftime(
                "%Y-%m-%d %H:%M:%S"
            )


            csv_writer.writerow([
                timestamp,
                dog_id,
                center_x,
                center_y,
                round(movement, 2),
                round(speed, 2),
                activity_level,
                round(confidence, 2)
            ])


            csv_output.flush()


    # ======================================
    # SHOW CAMERA
    # ======================================

    cv2.imshow(
        "Dog Movement + Activity",
        frame
    )


    # ======================================
    # PRESS Q TO EXIT
    # ======================================

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break


# ==========================================
# CLEANUP
# ==========================================

cap.release()

csv_output.close()

cv2.destroyAllWindows()

print("Dog Movement + Activity Analysis Stopped.")

print("Feature data saved to dog_features.csv")