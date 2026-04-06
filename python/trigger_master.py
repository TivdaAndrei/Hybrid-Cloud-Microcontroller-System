#!/usr/bin/env python3
import argparse
import time

import serial


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Send trigger '1' to Arduino master over USB serial"
    )
    parser.add_argument(
        "--port",
        default="/dev/ttyACM0",
        help="Serial device for master Arduino (default: /dev/ttyACM0)",
    )
    parser.add_argument(
        "--baud",
        type=int,
        default=9600,
        help="Baud rate (default: 9600)",
    )
    args = parser.parse_args()

    with serial.Serial(args.port, baudrate=args.baud, timeout=1) as ser:
        # Uno resets when serial port is opened
        time.sleep(2.0)
        ser.write(b"1")
        ser.flush()

    print(f"Sent trigger '1' to {args.port} at {args.baud} baud")


if __name__ == "__main__":
    main()
