# from ultralytics import YOLO
# import cv2

# # Load YOLO model
# model = YOLO("yolo11n.pt")

# # Open camera
# cap = cv2.VideoCapture(0)

# if not cap.isOpened():
#     print("ERROR: Camera could not be opened.")
#     exit()

# print("Dog Tracking Started")
# print("Press Q to quit.")

# while True:

#     ret, frame = cap.read()

#     if not ret:
#         print("ERROR: Could not read camera.")
#         break

#     # YOLO tracking
#     results = model.track(
#         frame,
#         persist=True,
#         classes=[16],
#         verbose=False
#     )

#     # Process result
#     for result in results:

#         if result.boxes is None:
#             continue

#         for box in result.boxes:

#             # Detection confidence
#             confidence = float(box.conf[0])

#             if confidence < 0.60:
#                 continue

#             # Dog tracking ID
#             if box.id is not None:

#                 track_id = int(box.id[0])

#             else:
#                 track_id = -1

#             # Bounding box
#             x1, y1, x2, y2 = map(int, box.xyxy[0])

#             # Draw bounding box
#             cv2.rectangle(
#                 frame,
#                 (x1, y1),
#                 (x2, y2),
#                 (0, 255, 0),
#                 2
#             )

#             # Display ID
#             label = f"Dog ID: {track_id}  {confidence:.2f}"

#             cv2.putText(
#                 frame,
#                 label,
#                 (x1, y1 - 10),
#                 cv2.FONT_HERSHEY_SIMPLEX,
#                 0.7,
#                 (0, 255, 0),
#                 2
#             )

#     # Display camera
#     cv2.imshow("Dog Tracking", frame)

#     # Quit
#     if cv2.waitKey(1) & 0xFF == ord("q"):
#         break

# cap.release()
# cv2.destroyAllWindows()

# print("Dog Tracking Stopped.")


from ultralytics import YOLO
import cv2
import os
import time

# Load YOLO model
model = YOLO("yolo11n.pt")

# Folder where dog images will be saved
save_folder = "dog_images"
os.makedirs(save_folder, exist_ok=True)

# Open camera
cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("ERROR: Camera could not be opened.")
    exit()

print("Dog Tracking Started")
print("Press Q to quit.")

# Store last save time for each dog ID
last_saved = {}

# Time interval between saved images of the same dog
SAVE_INTERVAL = 2

while True:

    ret, frame = cap.read()

    if not ret:
        print("ERROR: Could not read camera.")
        break

    # YOLO tracking
    results = model.track(
        frame,
        persist=True,
        classes=[16],      # 16 = dog
        verbose=False
    )

    # Process results
    for result in results:

        if result.boxes is None:
            continue

        for box in result.boxes:

            # Detection confidence
            confidence = float(box.conf[0])

            if confidence < 0.60:
                continue

            # Get tracking ID
            if box.id is not None:
                track_id = int(box.id[0])
            else:
                track_id = -1

            # Bounding box
            x1, y1, x2, y2 = map(int, box.xyxy[0])

            # Make sure coordinates are inside the frame
            x1 = max(0, x1)
            y1 = max(0, y1)
            x2 = min(frame.shape[1], x2)
            y2 = min(frame.shape[0], y2)

            # Draw bounding box
            cv2.rectangle(
                frame,
                (x1, y1),
                (x2, y2),
                (0, 255, 0),
                2
            )

            # Display ID and confidence
            label = f"Dog ID: {track_id}  {confidence:.2f}"

            cv2.putText(
                frame,
                label,
                (x1, y1 - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0),
                2
            )

            # -----------------------------------
            # SAVE DOG IMAGE WITH TRACKING ID
            # -----------------------------------

            if track_id != -1:

                current_time = time.time()

                # Check whether enough time has passed
                if (
                    track_id not in last_saved
                    or current_time - last_saved[track_id] >= SAVE_INTERVAL
                ):

                    # Crop only the dog
                    dog_image = frame[y1:y2, x1:x2]

                    # Make sure crop is not empty
                    if dog_image.size > 0:

                        # Count existing images for this ID
                        existing_files = [
                            f for f in os.listdir(save_folder)
                            if f.startswith(f"dog_ID_{track_id}_")
                        ]

                        image_number = len(existing_files) + 1

                        # File name
                        filename = (
                            f"dog_ID_{track_id}_{image_number:03d}.jpg"
                        )

                        filepath = os.path.join(
                            save_folder,
                            filename
                        )

                        # Save image
                        cv2.imwrite(filepath, dog_image)

                        print(f"Saved: {filepath}")

                        # Update last save time
                        last_saved[track_id] = current_time

    # Display camera
    cv2.imshow("Dog Tracking", frame)

    # Press Q to quit
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

# Release camera
cap.release()
cv2.destroyAllWindows()

print("Dog Tracking Stopped.")