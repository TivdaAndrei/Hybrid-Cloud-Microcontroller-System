# Arduino Uno Master/Slave Serial Chain Test

This project tests this communication path:

`Laptop -> Arduino Master -> Arduino Slave`

using only each board's built-in LED on pin 13.

## Hardware wiring

- Master `TX (pin 1)` -> Slave `RX (pin 0)`
- Master `RX (pin 0)` <- Slave `TX (pin 1)`
- Master `GND` <-> Slave `GND`

## Files

- `arduino/master/master.ino`: listens for `'1'`, blinks master LED, sends `BLINK`
- `arduino/slave/slave.ino`: listens for `BLINK`, blinks slave LED
- `python/trigger_master.py`: sends trigger byte `'1'` to master USB serial port

## Upload

- Upload `arduino/master/master.ino` to the master Uno.
- Upload `arduino/slave/slave.ino` to the slave Uno.

## Python setup (Ubuntu)

Install pyserial:

```bash
sudo apt update
sudo apt install -y python3-serial
```

Run trigger script:

```bash
python3 python/trigger_master.py --port /dev/ttyACM0 --baud 9600
```

Use `dmesg | tail` or `ls -l /dev/ttyACM*` to confirm which port is the master.

## Linux serial permissions (Ubuntu)

Recommended permanent access (without sudo):

```bash
sudo usermod -aG dialout $USER
newgrp dialout
```

Then unplug/replug both Arduinos (or log out/in).

Temporary quick workaround (resets on reconnect/reboot):

```bash
sudo chmod a+rw /dev/ttyACM0 /dev/ttyACM1
```

Optional persistent udev rule:

```bash
sudo tee /etc/udev/rules.d/99-arduino.rules >/dev/null <<'EOF'
SUBSYSTEM=="tty", ATTRS{idVendor}=="2341", MODE="0666", GROUP="dialout"
SUBSYSTEM=="tty", ATTRS{idVendor}=="2a03", MODE="0666", GROUP="dialout"
EOF

sudo udevadm control --reload-rules
sudo udevadm trigger
```

## Expected behavior

When you run the Python script:

1. Master receives `'1'` from laptop and blinks LED.
2. Master sends `BLINK` over TX/RX to slave.
3. Slave receives `BLINK` and blinks LED.

## Note about Arduino Uno serial

On Uno, USB serial and pins 0/1 are the same hardware UART. For this simple chain test, this setup is fine. Avoid opening multiple serial clients on the same device at once.
