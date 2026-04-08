#include <DHT.h>
#include <SoftwareSerial.h>

const int LED_PIN = 8;     // status LED (currently wired to D8)
const int DHT_PIN = 7;
const int DHT_TYPE = DHT11;
const int BUZZER_PIN = 6;  // passive piezo buzzer between D6 and GND

// Slave link via SoftwareSerial — same convention as the slave sketch.
//   master D10 (RX) <- slave D11 (TX)
//   master D11 (TX) -> slave D10 (RX)
const int SLAVE_RX_PIN = 10;
const int SLAVE_TX_PIN = 11;
SoftwareSerial slaveSerial(SLAVE_RX_PIN, SLAVE_TX_PIN);

DHT dht(DHT_PIN, DHT_TYPE);

unsigned long lastReadMs = 0;
const unsigned long READ_INTERVAL_MS = 2000;

// "Tadaa!" three-note ascending fanfare. Uses tone() so the buzzer must be
// PASSIVE (a tiny piezo disc), not the always-on active type.
void playTada() {
  tone(BUZZER_PIN, 659, 120);   // E5
  delay(140);
  tone(BUZZER_PIN, 988, 120);   // B5
  delay(140);
  tone(BUZZER_PIN, 1319, 280);  // E6
  delay(300);
  noTone(BUZZER_PIN);
}

void blinkLocalLed(int times = 2, int onMs = 120, int offMs = 120) {
  for (int i = 0; i < times; i++) {
    digitalWrite(LED_PIN, HIGH);
    delay(onMs);
    digitalWrite(LED_PIN, LOW);
    delay(offMs);
  }
}

void setup() {
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);
  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);

  Serial.begin(9600);
  slaveSerial.begin(9600);
  dht.begin();

  Serial.println("Master started");
  Serial.println("Reading DHT11 every 15 seconds...");
}

void loop() {
  // Check for incoming serial data for LED / buzzer control
  if (Serial.available() > 0) {
    char command = Serial.read();
    if (command == 'A') {
      digitalWrite(LED_PIN, HIGH);
      Serial.println("LED_STATUS:ON"); // Report status back
    } else if (command == 'S') {
      digitalWrite(LED_PIN, LOW);
      Serial.println("LED_STATUS:OFF"); // Report status back
    } else if (command == 'B') {
      playTada();
      Serial.println("BUZZER:TADA");
    }
  }

  // Drain any bytes coming from the slave and forward them up the USB
  // serial line so Flask sees POT:/SLED: messages exactly as before.
  while (slaveSerial.available() > 0) {
    Serial.write(slaveSerial.read());
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
      // Send data in a structured format
      Serial.print("DATA:T=");
      Serial.print(temperatureC, 2);
      Serial.print(":H=");
      Serial.print(humidity, 2);
      Serial.println();
    }
  }
}
