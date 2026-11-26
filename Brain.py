import json
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import paho.mqtt.client as mqtt
from gpiozero import OutputDevice


# ---------------- CONFIGURATION ----------------

BASE_DIR = Path.home() / "project"
DB_PATH = BASE_DIR / "database" / "smart_parking.db"
MODEL_PATH = BASE_DIR / "camera" / "helmet_mobilenetv2_v2.onnx"

# Anonymous MQTT - NO USERNAME OR PASSWORD
MQTT_BROKER = "localhost"
MQTT_PORT = 1883

TOPIC_CARD = "parking/card"
TOPIC_SLOTS = "parking/slots"
TOPIC_COMMAND = "parking/cmd"
TOPIC_HEARTBEAT = "parking/heartbeat"
TOPIC_NOTIFY = "parking/notify"

NUM_SLOTS = 4

# Helmet detection
HELMET_MODE = "camera"
HELMET_THRESHOLD = 0.75
REQUIRED_VOTES = 2
TOTAL_FRAMES = 3
CAMERA_INDEX = 0
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480

HEARTBEAT_GPIO = 17
HEARTBEAT_INTERVAL = 0.5
DUPLICATE_CARD_SECONDS = 3


# ---------------- SHARED STATE ----------------

state_lock = threading.Lock()
processing_lock = threading.Lock()

state = {
    "slots": None
}

last_card_uid = None
last_card_time = 0

client = None
helmet_net = None


# ---------------- DATABASE ----------------

def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def log_event(uid, name, result, reason):
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO events (time, uid, name, result, reason)
            VALUES (?, ?, ?, ?, ?)
        """, (
            datetime.now().isoformat(timespec="seconds"),
            uid,
            name,
            result,
            reason
        ))


def get_student(uid):
    with get_connection() as conn:
        return conn.execute("""
            SELECT student_id, name, parent_email
            FROM students
            WHERE uid = ?
        """, (uid,)).fetchone()


def get_active_session(uid):
    with get_connection() as conn:
        return conn.execute("""
            SELECT id
            FROM sessions
            WHERE uid = ? AND exit_time IS NULL
            ORDER BY id DESC
            LIMIT 1
        """, (uid,)).fetchone()


# ---------------- MQTT MESSAGES ----------------

def publish_notification(uid, name, result, reason, email=None):

    message = {
        "uid": uid,
        "name": name,
        "result": result,
        "reason": reason,
        "time": datetime.now().isoformat(timespec="seconds"),
        "parent_email": email
    }

    client.publish(
        TOPIC_NOTIFY,
        json.dumps(message),
        qos=1
    )


def send_result(uid, name, result, reason, command=None, email=None):

    log_event(uid, name, result, reason)

    if command:
        client.publish(
            TOPIC_COMMAND,
            command,
            qos=1
        )

    publish_notification(
        uid,
        name,
        result,
        reason,
        email
    )

    print(
        f"{result}: {name or 'Unknown student'} - {reason}"
    )


# ---------------- PARKING SLOT CHECK ----------------

def parse_slots(payload):

    value = payload.strip().replace(" ", "")

    if "," in value:
        values = value.split(",")
    elif len(value) == NUM_SLOTS:
        values = list(value)
    else:
        return None

    if len(values) != NUM_SLOTS:
        return None

    if any(item not in ("0", "1", "?") for item in values):
        return None

    return values


def get_slot_status():

    with state_lock:
        slots = state["slots"]

        if slots is None:
            return None, "Slot readings not received"

        slots = list(slots)

    if len(slots) != NUM_SLOTS:
        return None, "Invalid number of slot readings"

    if "?" in slots:
        return None, "One or more slot sensors unavailable"

    free_slots = slots.count("0")

    if free_slots == 0:
        return False, "Parking is full"

    return True, f"{free_slots} slot(s) available"


# ---------------- HELMET MODEL ----------------

def load_helmet_model():

    global helmet_net

    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"Helmet ONNX model not found: {MODEL_PATH}"
        )

    helmet_net = cv2.dnn.readNetFromONNX(str(MODEL_PATH))

    helmet_net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
    helmet_net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)

    print("Helmet ONNX model loaded successfully.")
    print("Helmet detection: OpenCV DNN CPU")


def classify_helmet(frame):

    if helmet_net is None:
        raise RuntimeError("Helmet model is not loaded")

    # Crop the region used during model preparation.
    cropped = frame[50:470, 140:500]

    if cropped.size == 0:
        raise ValueError("Invalid camera image crop")

    # Resize to model input dimensions.
    image = cv2.resize(
        cropped,
        (160, 160)
    )

    # Convert BGR to RGB.
    image = cv2.cvtColor(
        image,
        cv2.COLOR_BGR2RGB
    )

    # Normalize using ImageNet mean and standard deviation.
    image = image.astype(np.float32) / 255.0

    mean = np.array(
        [0.485, 0.456, 0.406],
        dtype=np.float32
    )

    std = np.array(
        [0.229, 0.224, 0.225],
        dtype=np.float32
    )

    image = (image - mean) / std

    # Convert HWC to NCHW.
    blob = np.transpose(
        image,
        (2, 0, 1)
    )

    blob = np.expand_dims(
        blob,
        axis=0
    ).astype(np.float32)

    helmet_net.setInput(blob)

    output = helmet_net.forward()

    # The ONNX model currently returns two raw class scores (logits).
    # Convert them to probabilities before applying the threshold.
    scores = np.array(output, dtype=np.float32).flatten()

    if len(scores) != 2:
        raise ValueError(
            f"Unexpected helmet model output: {scores}"
        )

    # Numerically stable softmax.
    exp_scores = np.exp(scores - np.max(scores))
    probabilities = exp_scores / np.sum(exp_scores)

    # Assumed class order: index 0 = helmet, index 1 = no helmet.
    helmet_score = float(probabilities[0])
    no_helmet_score = float(probabilities[1])

    return helmet_score, no_helmet_score


# ---------------- HELMET VERIFICATION ----------------

def check_helmet():

    if HELMET_MODE == "skip":
        print("Helmet detection skipped.")
        return True, "Helmet check skipped"

    print("Starting helmet verification...")

    camera = cv2.VideoCapture(CAMERA_INDEX)

    if not camera.isOpened():
        print("Camera could not be opened.")
        return False, "Camera unavailable"

    camera.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)

    helmet_votes = 0
    no_helmet_votes = 0
    uncertain_votes = 0

    try:

        # Allow camera exposure to stabilize.
        for _ in range(2):
            camera.read()

        for frame_number in range(TOTAL_FRAMES):

            success, frame = camera.read()

            if not success:
                print("Camera frame capture failed.")
                return False, "Camera frame capture failed"

            helmet_score, no_helmet_score = classify_helmet(frame)

            print(
                f"Helmet frame {frame_number + 1}: "
                f"H={helmet_score:.3f}, "
                f"NH={no_helmet_score:.3f}"
            )

            if helmet_score >= HELMET_THRESHOLD:
                helmet_votes += 1

            elif no_helmet_score >= HELMET_THRESHOLD:
                no_helmet_votes += 1

            else:
                uncertain_votes += 1


    except Exception as error:

        print("Helmet verification error:", error)

        return False, "Helmet verification failed"

    finally:
        camera.release()

    print(
        f"Helmet votes: {helmet_votes}/{TOTAL_FRAMES}"
    )

    print(
        f"No-helmet votes: {no_helmet_votes}/{TOTAL_FRAMES}"
    )

    print(
        f"Uncertain votes: {uncertain_votes}/{TOTAL_FRAMES}"
    )

    if helmet_votes >= REQUIRED_VOTES:

        print("Helmet verification PASSED.")

        return True, "Helmet detected successfully"

    if no_helmet_votes >= REQUIRED_VOTES:

        print("Helmet verification FAILED.")

        return False, "No helmet detected"

    print("Helmet verification inconclusive.")

    return False, "Helmet verification inconclusive"


# ---------------- RFID PROCESSING ----------------

def handle_card(uid):

    global last_card_uid, last_card_time

    with processing_lock:

        uid = uid.strip().upper()

        if not uid:
            return

        current_time = time.time()

        if (
            uid == last_card_uid
            and current_time - last_card_time
            < DUPLICATE_CARD_SECONDS
        ):

            print("Duplicate card tap ignored.")
            return

        last_card_uid = uid
        last_card_time = current_time

        print(f"\nRFID card detected: {uid}")

        student = get_student(uid)

        if student is None:

            send_result(
                uid,
                None,
                "DENIED",
                "Unregistered student",
                command="DENY_UNKNOWN"
            )

            return

        student_id, name, parent_email = student

        print(f"Student: {name} ({student_id})")

        # Check whether student is already inside.
        active_session = get_active_session(uid)

        if active_session:

            session_id = active_session[0]

            with get_connection() as conn:

                conn.execute("""
                    UPDATE sessions
                    SET exit_time = ?
                    WHERE id = ?
                """, (
                    datetime.now().isoformat(timespec="seconds"),
                    session_id
                ))

            send_result(
                uid,
                name,
                "EXIT",
                "Student exited successfully",
                command="OPEN",
                email=parent_email
            )

            return

        # Check parking availability.
        available, slot_message = get_slot_status()

        if available is not True:

            send_result(
                uid,
                name,
                "DENIED",
                slot_message,
                command="DENY_SLOT",
                email=parent_email
            )

            return

        # Verify helmet before entry.
        helmet_ok, helmet_message = check_helmet()

        if not helmet_ok:

            send_result(
                uid,
                name,
                "DENIED",
                helmet_message,
                command="DENY_HELMET",
                email=parent_email
            )

            return

        # Create parking session.
        with get_connection() as conn:

            conn.execute("""
                INSERT INTO sessions (uid, entry_time)
                VALUES (?, ?)
            """, (
                uid,
                datetime.now().isoformat(timespec="seconds")
            ))

        send_result(
            uid,
            name,
            "ENTRY",
            "Student entered successfully",
            command="OPEN",
            email=parent_email
        )


# ---------------- MQTT CALLBACKS ----------------

def on_connect(client, userdata, flags, reason_code, properties):

    if reason_code.is_failure:

        print("MQTT connection failed:", reason_code)
        return

    print("Connected to MQTT broker.")

    client.subscribe(TOPIC_CARD)
    client.subscribe(TOPIC_SLOTS)

    print("Subscribed to RFID and parking slot topics.")


def on_message(client, userdata, message):

    payload = message.payload.decode(
        "utf-8",
        errors="replace"
    ).strip()

    if message.topic == TOPIC_SLOTS:

        slots = parse_slots(payload)

        with state_lock:
            state["slots"] = slots

        if slots is None:
            print("Invalid slot message:", payload)

        else:
            print("Parking slots:", slots)

    elif message.topic == TOPIC_CARD:

        threading.Thread(
            target=handle_card,
            args=(payload,),
            daemon=True
        ).start()


# ---------------- HEARTBEAT ----------------

def heartbeat_loop():

    heartbeat_wire = None

    try:

        heartbeat_wire = OutputDevice(
            HEARTBEAT_GPIO,
            active_high=True,
            initial_value=False
        )

        print("GPIO17 heartbeat started.")

    except Exception as error:

        print("Physical heartbeat unavailable:", error)
        print("MQTT heartbeat will continue.")

    last_mqtt_heartbeat = 0

    try:

        while True:

            if heartbeat_wire is not None:

                try:
                    heartbeat_wire.toggle()

                except Exception as error:

                    print("GPIO heartbeat error:", error)

                    heartbeat_wire.close()
                    heartbeat_wire = None

            current_time = time.time()

            if current_time - last_mqtt_heartbeat >= 1:

                if client is not None and client.is_connected():

                    client.publish(
                        TOPIC_HEARTBEAT,
                        "1",
                        qos=0
                    )

                last_mqtt_heartbeat = current_time

            time.sleep(HEARTBEAT_INTERVAL)

    finally:

        if heartbeat_wire is not None:

            heartbeat_wire.off()
            heartbeat_wire.close()


# ---------------- MAIN PROGRAM ----------------

def main():

    global client

    if not DB_PATH.exists():

        raise FileNotFoundError(
            f"Database not found: {DB_PATH}"
        )

    # Verify database.
    with get_connection() as conn:

        conn.execute(
            "SELECT COUNT(*) FROM students"
        ).fetchone()

    # Load helmet model.
    load_helmet_model()

    # Anonymous MQTT client.
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id="smart-parking-pi"
    )

    client.on_connect = on_connect
    client.on_message = on_message

    print("Connecting to MQTT broker...")

    # No username_pw_set() call.
    client.connect(
        MQTT_BROKER,
        MQTT_PORT,
        keepalive=60
    )

    client.loop_start()

    threading.Thread(
        target=heartbeat_loop,
        daemon=True
    ).start()

    print("Smart Parking Raspberry Pi Brain is running.")
    print("Database:", DB_PATH)
    print("Helmet mode:", HELMET_MODE)
    print("Helmet threshold:", HELMET_THRESHOLD)
    print("Required votes:", REQUIRED_VOTES)
    print("Press Ctrl+C to stop.")

    try:

        while True:
            time.sleep(1)

    except KeyboardInterrupt:

        print("\nStopping Smart Parking Brain...")

    finally:

        client.loop_stop()
        client.disconnect()

        print("Program stopped.")


if __name__ == "__main__":
    main()
