#include <DHT.h>
#include <SoftwareSerial.h>

// --- Pin Definitions ---
const int LED_PIN = 13; // Built-in LED on Master
const int DHT_PIN = 7;
const int DHT_TYPE = DHT11;

// --- Software Serial for Slave Communication ---
// RX pin = 10, TX pin = 11
SoftwareSerial slaveSerial(10, 11);

// Buffer for assembling lines received from the Slave
String slaveBuffer = "";

// --- Objects ---
DHT dht(DHT_PIN, DHT_TYPE);

// --- Timing ---
unsigned long lastReadMs = 0;
const unsigned long READ_INTERVAL_MS = 2000;

void setup() {
  // Add a 4-second delay to allow for safe uploading
  delay(4000);

  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  // Serial to PC (Python)
  Serial.begin(9600);
  
  // Serial to Slave Arduino
  slaveSerial.begin(9600);
  
  dht.begin();

  Serial.println("Master started");
}

void loop() {
  // Check for incoming serial data from Python
  if (Serial.available() > 0) {
    char command = Serial.read();
    
    // Control Master's built-in LED
    if (command == 'A') {
      digitalWrite(LED_PIN, HIGH);
      Serial.println("LED_STATUS:ON");
    } else if (command == 'S') {
      digitalWrite(LED_PIN, LOW);
      Serial.println("LED_STATUS:OFF");
    }
    
    // Forward 'T' command to the Slave
    if (command == 'T') {
      slaveSerial.write('T');
      Serial.println("Sent Toggle command to Slave");
    }
  }

  // Read data from Slave and forward to Python
  while (slaveSerial.available() > 0) {
    char c = slaveSerial.read();
    if (c == '\n') {
      slaveBuffer.trim();
      Serial.println("RX< " + slaveBuffer);  // debug: print everything from slave
      if (slaveBuffer.startsWith("POT:")) {
        Serial.println(slaveBuffer);  // Forward: "POT:xxx"
      }
      slaveBuffer = "";
    } else {
      slaveBuffer += c;
    }
  }

  // Read sensor data at regular intervals
  unsigned long now = millis();
  if (now - lastReadMs >= READ_INTERVAL_MS) {
    lastReadMs = now;

    float humidity = dht.readHumidity();
    float temperatureC = dht.readTemperature();

    if (isnan(humidity) || isnan(temperatureC)) {
      Serial.println("DHT11 read failed");
    } else {
      // Send data to Python
      Serial.print("DATA:T=");
      Serial.print(temperatureC, 2);
      Serial.print(":H=");
      Serial.print(humidity, 2);
      Serial.println();
    }
  }
}