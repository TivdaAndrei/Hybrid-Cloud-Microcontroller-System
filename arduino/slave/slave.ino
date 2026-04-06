#include <string.h>

const int LED_PIN = 13;
char cmdBuffer[16];
byte idx = 0;

void blinkLocalLed(int times = 3, int onMs = 100, int offMs = 100) {
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
}

void loop() {
  while (Serial.available() > 0) {
    char ch = Serial.read();

    if (ch == '\n' || ch == '\r') {
      if (idx > 0) {
        cmdBuffer[idx] = '\0';
        if (strcmp(cmdBuffer, "BLINK") == 0) {
          blinkLocalLed();
        }
        idx = 0;
      }
    } else {
      if (idx < sizeof(cmdBuffer) - 1) {
        cmdBuffer[idx++] = ch;
      } else {
        idx = 0;
      }
    }
  }
}
