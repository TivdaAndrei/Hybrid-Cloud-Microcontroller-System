#include <DHT.h>

const int LED_PIN = 13;
const int DHT_PIN = 2;
const int DHT_TYPE = DHT11;

DHT dht(DHT_PIN, DHT_TYPE);

unsigned long lastReadMs = 0;
const unsigned long READ_INTERVAL_MS = 15000;

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
  Serial.begin(9600);
  dht.begin();

  Serial.println("Master started");
  Serial.println("Reading DHT11 every 15 seconds...");
}

void loop() {
  unsigned long now = millis();
  if (now - lastReadMs >= READ_INTERVAL_MS) {
    lastReadMs = now;

    float humidity = dht.readHumidity();
    float temperatureC = dht.readTemperature();

    if (isnan(humidity) || isnan(temperatureC)) {
      Serial.println("DHT11 read failed");
    } else {
      Serial.print("Temperature: ");
      Serial.print(temperatureC, 1);
      Serial.print(" C, Humidity: ");
      Serial.print(humidity, 1);
      Serial.println(" %");
    }
  }

  if (Serial.available() > 0) {
    char c = Serial.read();

    if (c == '1') {
      blinkLocalLed();
      Serial.println("BLINK");
    }
  }
}
