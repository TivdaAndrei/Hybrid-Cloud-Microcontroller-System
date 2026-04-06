#include <SoftwareSerial.h>

// --- Pin Definitions ---
// Potentiometer for controlling LED brightness
const int POT_PIN = A0; 
// External LED connected to a PWM pin (~)
const int PWM_LED_PIN = 9; 

// Pins for communication with the Master Arduino
const int RX_PIN = 10;
const int TX_PIN = 11;

// Set up the software serial port
SoftwareSerial masterSerial(RX_PIN, TX_PIN);

// --- Timing for sending pot value ---
unsigned long lastPotSendMs = 0;
const unsigned long POT_SEND_INTERVAL_MS = 200;

void setup() {
  // Add a 4-second delay to allow for safe uploading
  delay(4000);

  // Set the PWM LED pin as an output
  pinMode(PWM_LED_PIN, OUTPUT);
  
  // The built-in LED can be used for status blinks
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, LOW);

  // Start the software serial communication
  masterSerial.begin(9600);

  // Hardware Serial for debugging via USB Serial Monitor
  Serial.begin(9600);
  Serial.println("Slave started");
}

void loop() {
  // --- 1. Control LED brightness with the potentiometer ---
  int potValue = 1023 - analogRead(POT_PIN);
  int brightness = map(-potValue, 0, 1023, 0, 255);
  analogWrite(PWM_LED_PIN, brightness);

  // --- 2. Send pot value to Master every 200ms ---
  unsigned long now = millis();
  if (now - lastPotSendMs >= POT_SEND_INTERVAL_MS) {
    lastPotSendMs = now;
    String msg = "POT:" + String(potValue);
    masterSerial.println(msg);
    Serial.println("TX> " + msg);  // debug: confirm slave is sending
  }

  // --- 3. Listen for commands from the Master Arduino ---
  if (masterSerial.available() > 0) {
    char command = masterSerial.read();
    
    if (command == 'T') {
      // Toggle the built-in LED (pin 13) when command is received
      digitalWrite(LED_BUILTIN, !digitalRead(LED_BUILTIN));
      Serial.println("Toggle received from Master");
    }
  }

  // Small delay so SoftwareSerial pin-change interrupts are not starved
  // by continuous analogRead() calls (analogRead takes ~112us, same as
  // one bit period at 9600 baud, which can cause missed bytes).
  delay(10);
}