# Smart Two-Wheeler Parking System

An IoT-based smart parking system that automates two-wheeler entry and exit using RFID authentication, computer vision, ultrasonic sensors, and real-time communication.

## 1. Project Overview

Traditional campus parking systems often require manual student verification, helmet checks, and parking-space monitoring. This project aims to automate these processes using embedded systems and IoT technologies.

The system verifies student RFID cards, checks helmet compliance, monitors parking availability, controls an automated entry gate, and sends notifications to parents.

## 2. Key Features

- **RFID Authentication:** Identifies registered students using RFID cards.
- **Helmet Detection:** Uses a MobileNetV2-based machine learning model to identify helmet compliance.
- **Automated Gate Control:** Controls a servo motor based on the Raspberry Pi's access decision.
- **Smart Parking Monitoring:** Uses ultrasonic sensors to monitor parking-slot occupancy.
- **Real-Time Communication:** Uses MQTT over Wi-Fi to exchange data between the Raspberry Pi and Arduino.
- **Database Management:** Uses SQLite to store student information and parking sessions.
- **Live Dashboard:** Displays parking occupancy and system information.
- **Parent Notifications:** Uses Node-RED to process notification events and send email alerts.
- **Fault Tolerance:** Handles communication failures, invalid sensor readings, and unauthorised access.

## 3. Hardware Components

| Component | Purpose |
|---|---|
| Raspberry Pi | Central processing and decision-making |
| Arduino Nano 33 IoT | Hardware interfacing and control |
| MFRC522 RFID Reader | Reads student RFID cards |
| RFID Cards | Student identification |
| Ultrasonic Sensors | Detect parking-slot occupancy |
| USB Camera | Captures images for helmet detection |
| Servo Motor | Controls the parking gate |
| LEDs | Indicates system status |
| Buzzer | Provides audio feedback |

## 4. Software and Technologies

- **Python:** Main application logic on Raspberry Pi.
- **C++ (Arduino):** Hardware control and sensor interfacing.
- **OpenCV DNN:** Runs helmet detection inference.
- **MobileNetV2:** Machine learning architecture used for helmet classification.
- **ONNX:** Model deployment format.
- **MQTT / Mosquitto:** Lightweight messaging between devices.
- **SQLite:** Local database management.
- **Node-RED:** Notification workflow automation.
- **PyQt:** Desktop monitoring dashboard.
- **Wi-Fi:** Wireless communication between system components.

## 5. System Architecture

The system follows a distributed IoT architecture with centralised decision-making on the Raspberry Pi.

1. Arduino reads RFID cards and ultrasonic sensor values.
2. Arduino publishes the collected information to the MQTT broker.
3. Raspberry Pi receives the data and checks student registration in SQLite.
4. For a new entry, the Raspberry Pi captures an image and performs helmet detection.
5. The Raspberry Pi checks parking availability.
6. Based on the verification results, it publishes an access command through MQTT.
7. Arduino receives the command and controls the servo gate, LEDs, and buzzer.
8. Parking-slot updates are published to the monitoring dashboard.
9. Node-RED processes notification events and sends parent email alerts.

## 6. Working Process

### Entry Process

1. Student scans an RFID card.
2. Arduino reads the card UID and sends it to the Raspberry Pi through MQTT.
3. Raspberry Pi checks whether the student is registered.
4. The camera captures an image for helmet verification.
5. The ML model predicts whether the student is wearing a helmet.
6. The system checks whether a parking slot is available.
7. If all conditions are satisfied, the Raspberry Pi sends an `OPEN` command.
8. Arduino activates the servo motor and opens the gate.
9. The parking session is recorded in SQLite.

### Exit Process

1. Student scans the RFID card again.
2. Raspberry Pi identifies the existing active parking session.
3. The system processes the exit without repeating helmet verification.
4. The gate opens and the parking session is updated.

### Parking Monitoring

Ultrasonic sensors continuously measure the distance to nearby objects. The Arduino processes these readings and publishes slot occupancy information through MQTT.

The dashboard displays the current parking status.

## 7. MQTT Communication

MQTT is used for lightweight communication between the Raspberry Pi and Arduino.

Main topics include:

| MQTT Topic | Purpose |
|---|---|
| `parking/card` | Sends RFID card information |
| `parking/slots` | Publishes parking-slot status |
| `parking/cmd` | Sends gate control commands |
| `parking/heartbeat` | Monitors system connectivity |
| `parking/notify` | Sends notification events |

The Mosquitto MQTT broker runs on the Raspberry Pi.

## 8. Machine Learning Model

The helmet detection component uses MobileNetV2 for image classification.

- The model was trained using a labelled helmet and no-helmet image dataset.
- Training was performed in Google Colab.
- The trained model was exported to ONNX format.
- OpenCV DNN is used to perform inference on the Raspberry Pi.

The model is deployed separately from the training environment, allowing the Raspberry Pi to perform local inference.

## 9. Fault Tolerance and Safety

The system includes several mechanisms to improve reliability:

- **Heartbeat Monitoring:** Arduino monitors communication with the Raspberry Pi.
- **Safe Mode:** Access is denied when required communication becomes unavailable.
- **RFID Validation:** Unregistered cards are denied entry.
- **Parking Availability Check:** Entry is denied when parking is full.
- **Sensor Filtering:** Multiple ultrasonic readings are used to reduce incorrect occupancy decisions.
- **Invalid Reading Handling:** Invalid ultrasonic readings do not immediately overwrite the previous slot state.
- **MQTT Communication:** Devices exchange commands and status updates through a lightweight messaging protocol.

## 10. Demonstration Mode

For recording a demonstration video, helmet detection can be temporarily bypassed to demonstrate the remaining system functionality without requiring repeated camera-based verification.

This mode is intended only for controlled demonstrations. Helmet verification should be enabled during normal operation.

## 11. Project Structure

```text
Smart-Two-Wheeler-Parking/
│
├── Arduino_code.ino
│
├── RaspberryPi/
│   ├── brain.py
│   ├── camera/
│   │   └── helmet_mobilenetv2_v2.onnx
│   └── database/
│       └── smart_parking.db
│
├── Dashboard/
│   └── dashboard.py
│
├── Node-RED/
│   └── flow.json
│
└── README.md
```

## 12. Setup and Execution

### Prerequisites

- Raspberry Pi with Python installed
- Arduino IDE
- Mosquitto MQTT broker
- OpenCV
- Required Python dependencies
- Node-RED
- PyQt environment for the dashboard

### General Setup

1. Connect the RFID reader, ultrasonic sensors, servo motor, LEDs, and buzzer to the Arduino.
2. Configure the Wi-Fi credentials and MQTT broker address in the Arduino and Raspberry Pi code.
3. Install and start the Mosquitto MQTT broker.
4. Configure the SQLite database.
5. Place the ONNX model in the configured model directory.
6. Upload the Arduino sketch.
7. Run the Raspberry Pi application:

```bash
python3 brain.py
```

8. Import and deploy the Node-RED flow.
9. Start the desktop dashboard.

*Configure the correct paths, network settings, and dependencies before execution.*

## 13. Future Improvements

- Support a larger number of parking slots.
- Improve helmet detection using a larger and more diverse dataset.
- Introduce a web-based monitoring dashboard.
- Add cloud-based analytics and reporting.
- Implement stronger MQTT authentication and encrypted communication.
- Add automated system health monitoring.

## 14. Conclusion

This project demonstrates the integration of embedded systems, machine learning, IoT communication, database management, and automation to develop a smarter campus parking solution.

By combining RFID authentication, helmet detection, automated gate control, and real-time parking monitoring, the system reduces manual intervention and improves parking management.

---

**Project:** Smart Two-Wheeler Parking System  
**Domain:** Embedded Systems, IoT, Machine Learning, Automation  
**Communication Protocol:** MQTT over Wi-Fi
