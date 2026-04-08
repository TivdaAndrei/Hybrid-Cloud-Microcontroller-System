#include <SoftwareSerial.h>

// --- Pin Definitions ---
// External LED connected to a PWM pin (~).
// Wiring: pin 9 -> resistor -> LED anode (+), LED cathode (-) -> GND.
// With this wiring, pin HIGH = LED on and pin LOW = LED off. We always
// drive the pin LOW in the OFF state so the LED is fully extinguished.
const int PWM_LED_PIN = 9;

// KY-040 Rotary Encoder
//   CLK -> D2 (external interrupt INT0)
//   DT  -> D3
//   SW  -> D4 (push button, uses internal pull-up)
//   +   -> 5V
//   GND -> GND
const int ENC_CLK = 2;
const int ENC_DT  = 3;
const int ENC_SW  = 4;

// Pins for communication with the Master Arduino (SoftwareSerial)
//   slave D10 (RX) <- master D1 (TX)
//   slave D11 (TX) -> master D0 (RX)
const int RX_PIN = 10;
const int TX_PIN = 11;

SoftwareSerial masterSerial(RX_PIN, TX_PIN);

// --- Encoder / brightness state ---
volatile long encoderSteps = 0;     // accumulated steps from ISR (signed)
int  level      = 512;              // current brightness 0..1023 (starts ~50%)
int  savedLevel = 512;              // last brightness before LED was turned OFF
bool ledOn      = false;            // toggled by encoder push button
const int STEP  = 51;               // ~5% of 1023 per detent

// --- Button debounce state ---
// Stable-state debouncer: the button must hold its new reading for
// BTN_DEBOUNCE_MS before we accept it. A press is the HIGH->LOW transition
// of the *stable* state, so a single physical click can only fire once even
// if the contacts bounce dozens of times.
int btnStableState = HIGH;          // last accepted (debounced) state
int btnLastReading = HIGH;          // last raw digitalRead value
unsigned long btnLastChangeMs = 0;  // when the raw reading last changed
const unsigned long BTN_DEBOUNCE_MS = 50;

// --- Timing for sending state to master ---
unsigned long lastSendMs = 0;
const unsigned long SEND_INTERVAL_MS = 200;

// ISR: fires on falling edge of CLK. DT level tells us the direction.
void onEncoderISR() {
  if (digitalRead(ENC_DT) == HIGH) {
    encoderSteps++;   // clockwise (rotate right) -> brighter
  } else {
    encoderSteps--;   // counter-clockwise (rotate left) -> dimmer
  }
}

void setup() {
  // Add a 4-second delay to allow for safe uploading
  delay(4000);

  // Set the PWM LED pin as an output and force it LOW immediately so the
  // LED is dark from the moment the board powers up.
  pinMode(PWM_LED_PIN, OUTPUT);
  digitalWrite(PWM_LED_PIN, LOW);

  // Encoder pins (all use internal pull-ups)
  pinMode(ENC_CLK, INPUT_PULLUP);
  pinMode(ENC_DT,  INPUT_PULLUP);
  pinMode(ENC_SW,  INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(ENC_CLK), onEncoderISR, FALLING);

  // The built-in LED can be used for status blinks
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, LOW);

  // Start the SoftwareSerial link to the master
  masterSerial.begin(9600);

  // Hardware Serial for debugging via USB Serial Monitor
  Serial.begin(9600);
  Serial.println("Slave started");
}

void loop() {
  // --- 1. Drain encoder steps and update brightness (only when LED is ON) ---
  long steps;
  noInterrupts();
  steps = encoderSteps;
  encoderSteps = 0;
  interrupts();

  if (steps != 0 && ledOn) {
    level += (int)(steps * STEP);
    if (level < 0)    level = 0;
    if (level > 1023) level = 1023;
  }

  // --- 2. Debounced button read: toggle ledOn on the press edge ---
  // Reset the timer every time the raw reading changes; only accept the new
  // state once it has been stable for BTN_DEBOUNCE_MS. We act on the
  // HIGH -> LOW edge of the *debounced* state so a single click fires once.
  int reading = digitalRead(ENC_SW);
  if (reading != btnLastReading) {
    btnLastChangeMs = millis();
    btnLastReading  = reading;
  }
  if ((millis() - btnLastChangeMs) > BTN_DEBOUNCE_MS && reading != btnStableState) {
    btnStableState = reading;
    if (btnStableState == LOW) {    // confirmed press (active-low)
      if (ledOn) {
        // Turning OFF: remember the current brightness so we can restore it.
        savedLevel = level;
        ledOn = false;
      } else {
        // Turning ON: restore the brightness we had before the last OFF.
        level = savedLevel;
        ledOn = true;
      }
    }
  }

  // --- 3. Drive the PWM LED ---
  // OFF state: hard LOW on pin 9 (no PWM, no glow).
  // ON state:  PWM duty cycle proportional to `level`.
  if (!ledOn) {
    digitalWrite(PWM_LED_PIN, LOW);
  } else {
    int brightness = map(level, 0, 1023, 0, 255);
    if (brightness == 0) {
      digitalWrite(PWM_LED_PIN, LOW);
    } else if (brightness == 255) {
      digitalWrite(PWM_LED_PIN, HIGH);
    } else {
      analogWrite(PWM_LED_PIN, brightness);
    }
  }

  // --- 4. Send state to Master every 200ms ---
  unsigned long now = millis();
  if (now - lastSendMs >= SEND_INTERVAL_MS) {
    lastSendMs = now;

    masterSerial.print("POT:");
    masterSerial.println(level);

    masterSerial.print("SLED:");
    masterSerial.println(ledOn ? "ON" : "OFF");
  }

  // --- 5. Listen for commands from the Master Arduino ---
  if (masterSerial.available() > 0) {
    char command = masterSerial.read();

    if (command == 'T') {
      // Toggle the built-in LED (pin 13) when command is received
      digitalWrite(LED_BUILTIN, !digitalRead(LED_BUILTIN));
    }
  }

  // Small delay so SoftwareSerial pin-change interrupts are not starved.
  delay(10);
}
