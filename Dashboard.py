import os
import sys
import json
from datetime import datetime

import requests
import paho.mqtt.client as mqtt

from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QVBoxLayout,
    QHBoxLayout, QGridLayout, QFrame, QTableWidget,
    QTableWidgetItem, QHeaderView, QTabWidget
)


# ---------------- CONFIGURATION ----------------
# ---------------- CONFIGURATION ----------------

API_URL = "http://___:5000/api/dashboard"

BROKER = "__"
PORT = 1883
NUM_SLOTS = 4


# ---------------- MQTT SIGNALS ----------------

class MQTTSignals(QObject):

    slots_updated = pyqtSignal(list)
    event_received = pyqtSignal(dict)
    connection_changed = pyqtSignal(bool)


# ---------------- DASHBOARD ----------------

class ParkingDashboard(QMainWindow):

    def __init__(self):

        super().__init__()

        self.setWindowTitle("Smart Parking Management System")
        self.resize(1200, 760)

        self.signals = MQTTSignals()

        self.slots = [None] * NUM_SLOTS
        self.mqtt_connected = False
        self.current_students = []

        self.signals.slots_updated.connect(self.update_slots)
        self.signals.event_received.connect(self.refresh_data)
        self.signals.connection_changed.connect(
            self.update_connection_status
        )

        self.setup_ui()
        self.setup_mqtt()
        self.refresh_data()

        self.timer = QTimer()
        self.timer.timeout.connect(self.refresh_data)
        self.timer.start(2000)

    # ---------------- UI ----------------

    def setup_ui(self):

        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(22, 18, 22, 18)
        main_layout.setSpacing(15)

        header = QHBoxLayout()

        title = QLabel("SMART PARKING")
        title.setFont(QFont("Arial", 22, QFont.Bold))
        title.setStyleSheet("color: #16324F;")

        self.connection_label = QLabel("MQTT: Connecting...")
        self.connection_label.setStyleSheet(
            "color: #D97706; font-weight: bold;"
        )

        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.connection_label)

        main_layout.addLayout(header)

        subtitle = QLabel(
            "Live parking monitoring and student management"
        )
        subtitle.setStyleSheet("color: #64748B; font-size: 12px;")
        main_layout.addWidget(subtitle)

        summary = QGridLayout()
        summary.setSpacing(12)

        self.total_value = self.create_card(
            summary, 0, "TOTAL SLOTS", "4"
        )
        self.occupied_value = self.create_card(
            summary, 1, "OCCUPIED", "0"
        )
        self.available_value = self.create_card(
            summary, 2, "AVAILABLE", "4"
        )
        self.active_value = self.create_card(
            summary, 3, "ACTIVE SESSIONS", "0"
        )

        main_layout.addLayout(summary)

        self.tabs = QTabWidget()

        self.overview_tab = QWidget()
        self.students_tab = QWidget()
        self.sessions_tab = QWidget()
        self.events_tab = QWidget()

        self.tabs.addTab(self.overview_tab, "Overview")
        self.tabs.addTab(self.students_tab, "Students")
        self.tabs.addTab(self.sessions_tab, "Active Sessions")
        self.tabs.addTab(self.events_tab, "Event History")

        self.setup_overview()
        self.setup_students()
        self.setup_sessions()
        self.setup_events()

        main_layout.addWidget(self.tabs)

        self.footer = QLabel("Last updated: Waiting for data")
        self.footer.setStyleSheet(
            "color: #64748B; font-size: 11px;"
        )
        main_layout.addWidget(self.footer)

        self.setStyleSheet("""
            QMainWindow {
                background-color: #F1F5F9;
            }

            QTabWidget::pane {
                border: 1px solid #CBD5E1;
                background: white;
                border-radius: 6px;
            }

            QTabBar::tab {
                background: #E2E8F0;
                padding: 11px 20px;
                margin-right: 3px;
                color: #334155;
            }

            QTabBar::tab:selected {
                background: #16324F;
                color: white;
            }

            QTableWidget {
                background: white;
                border: none;
                gridline-color: #E2E8F0;
                selection-background-color: #DBEAFE;
                selection-color: #16324F;
            }

            QHeaderView::section {
                background: #E2E8F0;
                padding: 9px;
                border: none;
                font-weight: bold;
                color: #334155;
            }
        """)

    def create_card(self, layout, column, heading, value):

        card = QFrame()

        card.setStyleSheet("""
            QFrame {
                background: white;
                border: 1px solid #CBD5E1;
                border-radius: 8px;
            }
        """)

        card_layout = QVBoxLayout(card)

        label = QLabel(heading)
        label.setStyleSheet(
            "color: #64748B; font-size: 11px; font-weight: bold;"
        )

        number = QLabel(value)
        number.setFont(QFont("Arial", 25, QFont.Bold))
        number.setStyleSheet("color: #16324F;")

        card_layout.addWidget(label)
        card_layout.addWidget(number)

        layout.addWidget(card, 0, column)

        return number

    # ---------------- OVERVIEW ----------------

    def setup_overview(self):

        layout = QVBoxLayout(self.overview_tab)

        heading = QLabel("Parking Slot Status")
        heading.setFont(QFont("Arial", 15, QFont.Bold))
        heading.setStyleSheet("color: #16324F;")

        layout.addWidget(heading)

        self.slot_grid = QGridLayout()
        self.slot_grid.setSpacing(15)

        self.slot_labels = []

        for i in range(NUM_SLOTS):

            card = QFrame()
            card.setMinimumHeight(115)

            card_layout = QVBoxLayout(card)

            name = QLabel(f"SLOT {i + 1}")
            name.setAlignment(Qt.AlignCenter)
            name.setStyleSheet(
                "font-size: 14px; font-weight: bold;"
            )

            status = QLabel("WAITING")
            status.setAlignment(Qt.AlignCenter)
            status.setFont(QFont("Arial", 17, QFont.Bold))

            card_layout.addWidget(name)
            card_layout.addWidget(status)

            self.slot_grid.addWidget(card, i // 2, i % 2)
            self.slot_labels.append((card, status))

        layout.addLayout(self.slot_grid)
        layout.addStretch()

    # ---------------- TABLES ----------------

    def create_table(self, columns):

        table = QTableWidget()

        table.setColumnCount(len(columns))
        table.setHorizontalHeaderLabels(columns)

        table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch
        )

        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setAlternatingRowColors(True)

        return table

    def setup_students(self):

        layout = QVBoxLayout(self.students_tab)

        heading = QLabel("Registered Students")
        heading.setFont(QFont("Arial", 15, QFont.Bold))

        self.student_table = self.create_table([
            "Student ID / UID",
            "Name",
            "Parent Email"
        ])

        layout.addWidget(heading)
        layout.addWidget(self.student_table)

    def setup_sessions(self):

        layout = QVBoxLayout(self.sessions_tab)

        heading = QLabel("Currently Parked Students")
        heading.setFont(QFont("Arial", 15, QFont.Bold))

        self.session_table = self.create_table([
            "Student UID",
            "Student Name",
            "Entry Time"
        ])

        layout.addWidget(heading)
        layout.addWidget(self.session_table)

    def setup_events(self):

        layout = QVBoxLayout(self.events_tab)

        heading = QLabel("Recent Parking Events")
        heading.setFont(QFont("Arial", 15, QFont.Bold))

        self.event_table = self.create_table([
            "Time",
            "UID",
            "Name",
            "Event",
            "Reason"
        ])

        layout.addWidget(heading)
        layout.addWidget(self.event_table)

    # ---------------- MQTT ----------------

    def setup_mqtt(self):

        try:
            self.client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id="parking_dashboard"
            )

            self.client.on_connect = self.on_connect
            self.client.on_disconnect = self.on_disconnect
            self.client.on_message = self.on_message

            self.client.connect_async(BROKER, PORT, 60)
            self.client.loop_start()

        except Exception as error:
            self.connection_label.setText(
                f"MQTT error: {error}"
            )

    def on_connect(
        self, client, userdata, flags, reason_code, properties
    ):

        if reason_code == 0:

            client.subscribe("parking/slots")
            client.subscribe("parking/notify")

            self.signals.connection_changed.emit(True)

        else:

            self.signals.connection_changed.emit(False)

    def on_disconnect(
        self, client, userdata, disconnect_flags,
        reason_code, properties
    ):

        self.signals.connection_changed.emit(False)

    def on_message(self, client, userdata, message):

        try:

            payload = message.payload.decode("utf-8").strip()

            if message.topic == "parking/slots":

                raw_values = [
                    value.strip()
                    for value in payload.split(",")
                ]

                if (
                    len(raw_values) == NUM_SLOTS
                    and all(value in ("0", "1", "?")
                            for value in raw_values)
                ):

                    values = [
                        int(value) if value in ("0", "1") else None
                        for value in raw_values
                    ]

                    self.signals.slots_updated.emit(values)

            elif message.topic == "parking/notify":

                data = json.loads(payload)

                if isinstance(data, dict):
                    self.signals.event_received.emit(data)

        except Exception as error:

            print("MQTT message error:", error)

    # ---------------- SLOT DISPLAY ----------------

    def update_slots(self, values):

        self.slots = values

        for index, value in enumerate(values):

            card, label = self.slot_labels[index]

            if value == 1:

                label.setText("OCCUPIED")

                card.setStyleSheet("""
                    QFrame {
                        background: #FEE2E2;
                        border: 2px solid #DC2626;
                        border-radius: 8px;
                    }
                """)

                label.setStyleSheet(
                    "color: #B91C1C; font-weight: bold;"
                )

            elif value == 0:

                label.setText("FREE")

                card.setStyleSheet("""
                    QFrame {
                        background: #DCFCE7;
                        border: 2px solid #16A34A;
                        border-radius: 8px;
                    }
                """)

                label.setStyleSheet(
                    "color: #15803D; font-weight: bold;"
                )

            else:

                label.setText("UNKNOWN")

                card.setStyleSheet("""
                    QFrame {
                        background: #F1F5F9;
                        border: 2px solid #64748B;
                        border-radius: 8px;
                    }
                """)

                label.setStyleSheet(
                    "color: #475569; font-weight: bold;"
                )

        occupied = sum(value == 1 for value in values)
        available = sum(value == 0 for value in values)

        self.total_value.setText(str(NUM_SLOTS))
        self.occupied_value.setText(str(occupied))
        self.available_value.setText(str(available))

    # ---------------- DATABASE / API ----------------

    def refresh_data(self, event=None):

        try:

            response = requests.get(API_URL, timeout=3)
            response.raise_for_status()

            data = response.json()

            if "error" in data:
                raise Exception(data["error"])

            self.current_students = data["students"]

            self.load_students(data["students"])
            self.load_sessions(data["sessions"])
            self.load_events(data["events"])

            self.footer.setText(
                "Last updated: " +
                datetime.now().strftime("%d-%m-%Y %H:%M:%S")
            )

        except Exception as error:

            print("API error:", error)

            self.footer.setText(
                "API connection error: " + str(error)
            )

    def load_students(self, rows):

        self.student_table.setRowCount(len(rows))

        for row_index, row in enumerate(rows):

            values = [
                row["uid"],
                row["name"],
                row["parent_email"]
            ]

            for column, value in enumerate(values):

                self.student_table.setItem(
                    row_index,
                    column,
                    QTableWidgetItem(str(value or ""))
                )

    def load_sessions(self, rows):

        active_sessions = [
            row for row in rows
            if row["exit_time"] is None
        ]

        self.session_table.setRowCount(len(active_sessions))
        self.active_value.setText(str(len(active_sessions)))

        student_names = {
            row["uid"]: row["name"]
            for row in self.current_students
        }

        for row_index, row in enumerate(active_sessions):

            values = [
                row["uid"],
                student_names.get(row["uid"], "Unknown"),
                row["entry_time"]
            ]

            for column, value in enumerate(values):

                self.session_table.setItem(
                    row_index,
                    column,
                    QTableWidgetItem(str(value or ""))
                )

    def load_events(self, rows):

        self.event_table.setRowCount(min(len(rows), 50))

        for row_index, row in enumerate(rows[:50]):

            values = [
                row["time"],
                row["uid"] or "",
                row["name"] or "",
                row["result"],
                row["reason"] or ""
            ]

            for column, value in enumerate(values):

                self.event_table.setItem(
                    row_index,
                    column,
                    QTableWidgetItem(str(value))
                )

    # ---------------- CONNECTION STATUS ----------------

    def update_connection_status(self, connected):

        self.mqtt_connected = connected

        if connected:

            self.connection_label.setText("MQTT: CONNECTED")
            self.connection_label.setStyleSheet(
                "color: #15803D; font-weight: bold;"
            )

        else:

            self.connection_label.setText("MQTT: DISCONNECTED")
            self.connection_label.setStyleSheet(
                "color: #DC2626; font-weight: bold;"
            )

    # ---------------- SHUTDOWN ----------------

    def closeEvent(self, event):

        self.timer.stop()

        if hasattr(self, "client"):

            self.client.loop_stop()
            self.client.disconnect()

        event.accept()


# ---------------- APPLICATION ----------------

if __name__ == "__main__":

    app = QApplication(sys.argv)

    window = ParkingDashboard()
    window.show()

    sys.exit(app.exec_())
