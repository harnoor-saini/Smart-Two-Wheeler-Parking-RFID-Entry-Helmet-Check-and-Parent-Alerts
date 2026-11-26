#include <SPI.h>
#include <MFRC522.h>
#include <Servo.h>
#include <WiFiNINA.h>
#include <ArduinoMqttClient.h>

// ---------- NETWORK ----------
const char WIFI_SSID[] = "___";
const char WIFI_PASS[] = "___";

const char BROKER_HOST[] = "___";
const int BROKER_PORT = 1883;

// ---------- PINS ----------
#define SS_PIN 10
#define RST_PIN 9

#define RED 5
#define GREEN 6
#define YELLOW 7
#define SERVO_PIN 4
#define BUZZER 8
#define HB_PIN A5

#define GATE_CLOSED 90
#define GATE_OPEN 0
#define GATE_OPEN_MS 4000

#define HB_TIMEOUT_MS 5000
#define HB_WIRE_TIMEOUT_MS 3000

#define USE_HEARTBEAT 1
#define USE_HB_WIRE 1

// ---------- PARKING SLOTS ----------
#define NUM_SLOTS 4
#define NEED_AGREE 3

const int trigPins[NUM_SLOTS] = {0, 1, 3, A4};
const int echoPins[NUM_SLOTS] = {A0, A1, A2, A3};

const int OCCUPIED_CM = 10;

bool slotOccupied[NUM_SLOTS] = {false, false, false, false};
bool slotKnown[NUM_SLOTS] = {false, false, false, false};

int streak[NUM_SLOTS] = {0, 0, 0, 0};

// ---------- OBJECTS ----------
MFRC522 rfid(SS_PIN, RST_PIN);
Servo gate;

WiFiClient wifi;
MqttClient mqtt(wifi);

// ---------- STATE ----------
String pendingCmd = "";

unsigned long lastHeartbeatMs = 0;
bool gotHeartbeat = false;

volatile unsigned long lastHbEdgeMs = 0;

bool wasSafe = true;

unsigned long nextConnectTry = 0;
unsigned long lastSlotCheck = 0;
unsigned long lastSlotPublish = 0;
unsigned long lastWarnBeep = 0;

// ---------- HEARTBEAT WIRE ----------
void hbEdge() {
  lastHbEdgeMs = millis();
}

// ---------- ULTRASONIC SENSOR ----------
float readOnce(int slot) {

  digitalWrite(trigPins[slot], LOW);
  delayMicroseconds(2);

  digitalWrite(trigPins[slot], HIGH);
  delayMicroseconds(10);

  digitalWrite(trigPins[slot], LOW);

  long duration = pulseIn(echoPins[slot], HIGH, 15000);

  if (duration == 0) {
    return -1;
  }

  return duration * 0.0343 / 2.0;
}

float readDistanceCm(int slot) {

  float vals[3];
  int n = 0;

  for (int r = 0; r < 3; r++) {

    float cm = readOnce(slot);

    if (cm > 0) {
      vals[n++] = cm;
    }

    delay(25);
  }

  if (n == 0) {
    return -1;
  }

  // Sort readings to calculate median
  for (int i = 1; i < n; i++) {

    float key = vals[i];
    int j = i - 1;

    while (j >= 0 && vals[j] > key) {
      vals[j + 1] = vals[j];
      j--;
    }

    vals[j + 1] = key;
  }

  return vals[n / 2];
}

// ---------- SLOT STATUS ----------
String slotsString() {

  String result = "";

  for (int i = 0; i < NUM_SLOTS; i++) {

    if (i > 0) {
      result += ",";
    }

    if (!slotKnown[i]) {
      result += "?";
    } else {
      result += slotOccupied[i] ? "1" : "0";
    }
  }

  return result;
}

// ---------- MQTT HELPERS ----------
void publishText(const char* topic, String payload, bool retain) {

  if (!mqtt.connected()) {
    return;
  }

  mqtt.beginMessage(topic, retain);
  mqtt.print(payload);
  mqtt.endMessage();
}

void publishSlots() {

  publishText("parking/slots", slotsString(), true);

  lastSlotPublish = millis();
}

void onMessage(int size) {

  String topic = mqtt.messageTopic();
  String msg = "";

  while (mqtt.available()) {
    msg += (char)mqtt.read();
  }

  msg.trim();

  if (topic == "parking/heartbeat") {

    lastHeartbeatMs = millis();
    gotHeartbeat = true;

  } else if (topic == "parking/cmd") {

    pendingCmd = msg;
  }
}

// ---------- SAFETY ----------
bool safeMode() {

  bool linkOk =
    (WiFi.status() == WL_CONNECTED && mqtt.connected());

  bool mqttHbOk = true;

#if USE_HEARTBEAT
  mqttHbOk =
    gotHeartbeat &&
    (millis() - lastHeartbeatMs < HB_TIMEOUT_MS);
#endif

  bool wireOk = true;

#if USE_HB_WIRE
  unsigned long nowMs = millis();
  unsigned long edgeMs = lastHbEdgeMs;

  wireOk =
    ((long)(nowMs - edgeMs) < (long)HB_WIRE_TIMEOUT_MS);
#endif

  return !(linkOk && mqttHbOk && wireOk);
}

// ---------- WI-FI AND MQTT ----------
void maintainConnection() {

  if (WiFi.status() == WL_CONNECTED && mqtt.connected()) {
    return;
  }

  if (millis() < nextConnectTry) {
    return;
  }

  nextConnectTry = millis() + 10000;

  if (WiFi.status() != WL_CONNECTED) {

    Serial.println("Connecting to Wi-Fi...");

    WiFi.begin(WIFI_SSID, WIFI_PASS);

    if (WiFi.status() != WL_CONNECTED) {
      return;
    }

    Serial.print("Wi-Fi connected, IP: ");
    Serial.println(WiFi.localIP());
  }

  Serial.println("Connecting to MQTT broker...");

  mqtt.setId("parking-arduino");
  mqtt.onMessage(onMessage);

  // Anonymous MQTT connection
  if (mqtt.connect(BROKER_HOST, BROKER_PORT)) {

    mqtt.subscribe("parking/cmd");
    mqtt.subscribe("parking/heartbeat");

    Serial.println("MQTT broker connected");

    publishSlots();

  } else {

    Serial.println("MQTT connection failed");
    Serial.print("MQTT error: ");
    Serial.println(mqtt.connectError());
  }
}

// ---------- GATE, LEDS AND BUZZER ----------
void beep(int times) {

  for (int i = 0; i < times; i++) {

    digitalWrite(BUZZER, HIGH);
    delay(150);

    digitalWrite(BUZZER, LOW);
    delay(150);
  }
}

void openGate() {

  digitalWrite(GREEN, HIGH);

  gate.write(GATE_OPEN);
  delay(GATE_OPEN_MS);

  gate.write(GATE_CLOSED);
  delay(600);

  digitalWrite(GREEN, LOW);
}

void denyEntry() {

  digitalWrite(RED, HIGH);

  beep(3);
  delay(500);

  digitalWrite(RED, LOW);
}

// ---------- HANDLE PI COMMANDS ----------
void handleCommand(String cmd) {

  Serial.print("Command from Pi: ");
  Serial.println(cmd);

  if (cmd == "OPEN") {

    if (safeMode()) {

      Serial.println("Ignored: SAFE MODE");

    } else {

      openGate();
    }

  } else if (cmd.startsWith("DENY")) {

    denyEntry();

  } else {

    Serial.println("Unknown command");
  }
}

// ---------- SETUP ----------
void setup() {

  Serial.begin(115200);

  pinMode(RED, OUTPUT);
  pinMode(GREEN, OUTPUT);
  pinMode(YELLOW, OUTPUT);
  pinMode(BUZZER, OUTPUT);

  pinMode(HB_PIN, INPUT_PULLDOWN);

  digitalWrite(BUZZER, LOW);
  digitalWrite(RED, LOW);
  digitalWrite(GREEN, LOW);
  digitalWrite(YELLOW, HIGH);

  for (int i = 0; i < NUM_SLOTS; i++) {

    pinMode(trigPins[i], OUTPUT);
    pinMode(echoPins[i], INPUT_PULLDOWN);

    digitalWrite(trigPins[i], LOW);
  }

  gate.attach(SERVO_PIN);
  gate.write(GATE_CLOSED);

  SPI.begin();
  rfid.PCD_Init();

  lastHbEdgeMs = millis();

#if USE_HB_WIRE
  attachInterrupt(
    digitalPinToInterrupt(HB_PIN),
    hbEdge,
    CHANGE
  );
#endif

  Serial.println("Parking node starting");
  Serial.println("Broker: 192.168.1.9");
  Serial.println("MQTT authentication: Disabled");
}

// ---------- MAIN LOOP ----------
void loop() {

  maintainConnection();

  if (mqtt.connected()) {
    mqtt.poll();
  }

  // Safety mode
  bool safe = safeMode();

  digitalWrite(YELLOW, safe ? HIGH : LOW);

  if (safe != wasSafe) {

    Serial.println(
      safe
        ? "SAFE MODE: Pi not responding, entry locked"
        : "Normal mode: Pi connected"
    );

    wasSafe = safe;
  }

  if (safe && millis() - lastWarnBeep > 10000) {

    lastWarnBeep = millis();
    beep(1);
  }

  // Check parking slots once per second
  if (millis() - lastSlotCheck > 1000) {

    lastSlotCheck = millis();

    bool changed = false;

    for (int i = 0; i < NUM_SLOTS; i++) {

      float cm = readDistanceCm(i);

      // No valid echo: preserve previous state
      if (cm < 0) {

        streak[i] = 0;
        continue;
      }

      bool occupied = (cm >= 2 && cm < OCCUPIED_CM);

      if (occupied == slotOccupied[i] && slotKnown[i]) {

        streak[i] = 0;

      } else {

        streak[i]++;

        if (streak[i] >= NEED_AGREE) {

          slotOccupied[i] = occupied;
          slotKnown[i] = true;

          streak[i] = 0;
          changed = true;

          Serial.print("Slot ");
          Serial.print(i + 1);
          Serial.println(occupied ? " now OCCUPIED" : " now FREE");
        }
      }

      delay(60);
    }

    if (changed || millis() - lastSlotPublish > 5000) {
      publishSlots();
    }
  }

  // Handle commands from Raspberry Pi
  if (pendingCmd != "") {

    String cmd = pendingCmd;
    pendingCmd = "";

    handleCommand(cmd);
  }

  // RFID card reading
  if (rfid.PICC_IsNewCardPresent() &&
      rfid.PICC_ReadCardSerial()) {

    String uid = "";

    for (byte i = 0; i < rfid.uid.size; i++) {

      if (rfid.uid.uidByte[i] < 0x10) {
        uid += "0";
      }

      uid += String(rfid.uid.uidByte[i], HEX);
    }

    uid.toUpperCase();

    Serial.print("Card UID: ");
    Serial.println(uid);

    if (safeMode()) {

      Serial.println("CARD REJECTED: SAFE MODE");
      denyEntry();

    } else {

      publishText("parking/card", uid, false);

      Serial.println("Card UID sent to Raspberry Pi");
      Serial.println("Waiting for Pi decision...");
    }

    rfid.PICC_HaltA();
    rfid.PCD_StopCrypto1();
  }
}
