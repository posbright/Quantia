
import os
import mss
import cv2
import numpy as np
import time
import glob
from ultralytics import YOLO
from openpyxl import Workbook

# Ensure necessary directories exist
save_path = "./"
screenshots_path = os.path.join(save_path, "screenshots")
detect_path = os.path.join(save_path, "runs/detect/")

os.makedirs(save_path, exist_ok=True)
os.makedirs(screenshots_path, exist_ok=True)

# Define pattern classes
classes = ['Head and shoulders bottom', 'Head and shoulders top', 'M_Head', 'StockLine', 'Triangle', 'W_Bottom']

# Load YOLOv8 model
model_path = "model.pt"
if not os.path.exists(model_path):
    raise FileNotFoundError(f"Model file not found: {model_path}")
model = YOLO(model_path)

# Define screen capture region
monitor = {"top": 0, "left": 683, "width": 683, "height": 768}

# Create an Excel file
excel_file = os.path.join(save_path, "classification_results.xlsx")
wb = Workbook()
ws = wb.active
ws.append(["Timestamp", "Predicted Image Path", "Label"])  # Headers

# Initialize video writer
video_path = "./video/annotated_video.mp4"
fourcc = cv2.VideoWriter_fourcc(*"mp4v")
fps = 0.5  # Adjust frames per second as needed
video_writer = None

# Start capturing
with mss.mss() as sct:
    start_time = time.time()
    last_capture_time = start_time  # Track the last capture time
    frame_count = 0
    
    while True:
        # Continuously capture the screen
        sct_img = sct.grab(monitor)
        img = np.array(sct_img)
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

        # Check if 60 seconds have passed since last YOLO prediction
        current_time = time.time()
        if current_time - last_capture_time >= 60:
            # Take screenshot for YOLO prediction
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            image_name = f"predicted_images_{timestamp}_{frame_count}.png"
            image_path = os.path.join(screenshots_path, image_name)
            cv2.imwrite(image_path, img)

            # Run YOLO model and get save directory
            results = model(image_path, save=True)
            predict_path = results[0].save_dir if results else None

            # Find the latest annotated image inside predict_path
            if predict_path and os.path.exists(predict_path):
                annotated_images = sorted(glob.glob(os.path.join(predict_path, "*.jpg")), key=os.path.getmtime, reverse=True)
                final_image_path = annotated_images[0] if annotated_images else image_path
            else:
                final_image_path = image_path  # Fallback to original image

            # Determine predicted label
            if results and results[0].boxes:
                class_indices = results[0].boxes.cls.tolist()
                predicted_label = classes[int(class_indices[0])]
            else:
                predicted_label = "No pattern detected"

            # Insert data into Excel (store path instead of image)
            ws.append([timestamp, final_image_path, predicted_label])

            # Read the image for video processing
            annotated_img = cv2.imread(final_image_path)
            if annotated_img is not None:
                # Add timestamp and label text to the image
                font = cv2.FONT_HERSHEY_SIMPLEX
                cv2.putText(annotated_img, f"{timestamp}", (10, 30), font, 0.7, (0, 255, 0), 2, cv2.LINE_AA)
                cv2.putText(annotated_img, f"{predicted_label}", (10, 60), font, 0.7, (0, 255, 255), 2, cv2.LINE_AA)
                
                # Initialize video writer if not already initialized
                if video_writer is None:
                    height, width, layers = annotated_img.shape
                    video_writer = cv2.VideoWriter(video_path, fourcc, fps, (width, height))
                
                video_writer.write(annotated_img)

            print(f"Frame {frame_count}: {final_image_path} -> {predicted_label}")
            frame_count += 1

            # Update the last capture time
            last_capture_time = current_time

        # Save the Excel file periodically
        wb.save(excel_file)

        # If you want to continuously display the screen, you can add this line
        cv2.imshow("Screen Capture", img)

        # Break if 'q' is pressed (you can exit the loop this way)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

# Release video writer
if video_writer is not None:
    video_writer.release()
    print(f"Video saved at {video_path}")

# Remove all files in screenshots directory
for file in os.scandir(screenshots_path):
    os.remove(file.path)
os.rmdir(screenshots_path)

print(f"Results saved to {excel_file}")

# Close OpenCV window
cv2.destroyAllWindows()