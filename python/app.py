from flask import Flask, render_template, jsonify
import serial
import threading
import time
import re

app = Flask(__name__)

# --- Data Storage ---
# A thread-safe way to store the latest sensor data
sensor_data = {
    'temperature': 'N/A',
    'humidity': 'N/A',
    'error': 'Initializing...'
}
data_lock = threading.Lock()

# --- Background Thread for Arduino Communication ---
def read_from_arduino():
    """
    Reads data from the Arduino in a separate thread to avoid blocking the web server.
    """
    global sensor_data
    while True:
        try:
            # --- IMPORTANT: Change 'COM3' to your master Arduino's COM port ---
            ser = serial.Serial('COM7', 9600, timeout=2)
            print("Arduino connected.")
            with data_lock:
                sensor_data['error'] = None
            
            while True:
                line = ser.readline().decode('utf-8').strip()
                if line.startswith("DATA:T="):
                    # Use regex to find floating point numbers for temp and humidity
                    match = re.search(r"DATA:T=([\d.]+):H=([\d.]+)", line)
                    if match:
                        temp = match.group(1)
                        hum = match.group(2)
                        with data_lock:
                            sensor_data['temperature'] = f"{float(temp):.2f}"
                            sensor_data['humidity'] = f"{float(hum):.2f}"
                            sensor_data['error'] = None
                        print(f"Data updated: Temp={temp}, Hum={hum}")
                elif line.startswith("LED_STATUS:"):
                    status = line.split(':')[1]
                    with data_lock:
                        sensor_data['led_status'] = status
                    print(f"LED status updated: {status}")
                time.sleep(0.1) # Small delay to prevent high CPU usage

        except serial.SerialException as e:
            print(f"Error: {e}. Is the Arduino connected?")
            with data_lock:
                sensor_data['error'] = "Arduino not connected. Retrying..."
                sensor_data['temperature'] = 'N/A'
                sensor_data['humidity'] = 'N/A'
            time.sleep(5) # Wait 5 seconds before trying to reconnect

# --- Flask Routes ---
@app.route('/')
def index():
    """
    Renders the main HTML page.
    """
    return render_template('index.html')

@app.route('/data')
def get_data():
    """
    Provides the latest sensor data as a JSON object.
    This is what the frontend will call to get updates.
    """
    with data_lock:
        return jsonify(sensor_data)

if __name__ == '__main__':
    # Start the background thread that reads from the Arduino
    arduino_thread = threading.Thread(target=read_from_arduino, daemon=True)
    arduino_thread.start()
    
    # Start the Flask web server
    # Use host='0.0.0.0' to make it accessible from other devices on your network
    app.run(host='0.0.0.0', port=5000, debug=False)
