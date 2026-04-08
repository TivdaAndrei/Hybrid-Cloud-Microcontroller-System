from flask import Flask, render_template, jsonify, request
import serial
import threading
import time
import re
import os
import math
import json
import queue
from datetime import datetime

from ollama_agent import analyze as ollama_analyze, voice_command as ollama_voice_command

app = Flask(__name__)

AI_INTERVAL_SECONDS = int(os.environ.get('AI_INTERVAL_SECONDS', '30'))
AI_LOG_MAX = 20

# --- Face recognition storage ---
FACE_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'users.json')
# Euclidean-distance threshold for matching face descriptors. face-api.js
# uses 0.6 by default; 0.5 is a bit stricter and reduces false positives.
FACE_MATCH_THRESHOLD = float(os.environ.get('FACE_MATCH_THRESHOLD', '0.5'))
face_lock = threading.Lock()

# --- NFC tag storage ---
TAG_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tags.json')
nfc_lock = threading.Lock()
nfc_state = {
    'last_uid': None,
    'last_seen_at': None,
    'matched_name': None,
}


def _load_tag_db():
    """Return list of {name, uid} from disk. Empty list if missing/corrupt."""
    try:
        with open(TAG_DB_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return []


def _save_tag_db(tags):
    with open(TAG_DB_PATH, 'w', encoding='utf-8') as f:
        json.dump(tags, f)


def _lookup_tag(uid):
    """Return the enrolled name for a UID, or None."""
    uid = (uid or '').upper()
    if not uid:
        return None
    for t in _load_tag_db():
        if t.get('uid', '').upper() == uid:
            return t.get('name')
    return None


def _load_face_db():
    """Return list of {name, descriptor} from disk. Empty list if missing/corrupt."""
    try:
        with open(FACE_DB_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return []


def _save_face_db(users):
    with open(FACE_DB_PATH, 'w', encoding='utf-8') as f:
        json.dump(users, f)


def _euclidean(a, b):
    if len(a) != len(b):
        return float('inf')
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))

# --- Command Queue (for sending commands to Arduino from Flask routes) ---
command_queue = queue.Queue()

# --- Data Storage ---
# A thread-safe way to store the latest sensor data
sensor_data = {
    'temperature': 'N/A',
    'humidity': 'N/A',
    'led_status': 'N/A',
    'slave_led_status': 'N/A',
    'pot_value': 'N/A',
    'error': 'Initializing...'
}
data_lock = threading.Lock()

# --- AI Agent State ---
ai_state = {
    'enabled': True,
    'last_run': None,        # ISO timestamp of last analysis
    'last_decision': None,   # last decision dict from ollama_agent.analyze
    'log': []                # bounded list of recent {timestamp, snapshot, decision, executed}
}
ai_lock = threading.Lock()


def _snapshot_sensors():
    with data_lock:
        return dict(sensor_data)


def _apply_decision(decision, snapshot):
    """Translate a decision dict into a serial command, if appropriate.

    Returns True if a command was actually queued."""
    action = decision.get('action', 'none')
    led_status = str(snapshot.get('led_status', '')).strip().upper()
    if action == 'led_on' and led_status != 'ON':
        command_queue.put('A')
        return True
    if action == 'led_off' and led_status != 'OFF':
        command_queue.put('S')
        return True
    return False


def _record_ai_run(snapshot, decision, executed):
    entry = {
        'timestamp': datetime.now().isoformat(timespec='seconds'),
        'snapshot': snapshot,
        'decision': decision,
        'executed': executed,
    }
    with ai_lock:
        ai_state['last_run'] = entry['timestamp']
        ai_state['last_decision'] = decision
        ai_state['log'].append(entry)
        if len(ai_state['log']) > AI_LOG_MAX:
            ai_state['log'] = ai_state['log'][-AI_LOG_MAX:]


def run_single_analysis():
    """Run one Ollama analysis cycle. Safe to call from any thread."""
    snapshot = _snapshot_sensors()
    if snapshot.get('error'):
        decision = {'action': 'none', 'reason': 'Arduino offline; skipping analysis.'}
        _record_ai_run(snapshot, decision, False)
        return decision
    decision = ollama_analyze(snapshot)
    executed = _apply_decision(decision, snapshot)
    _record_ai_run(snapshot, decision, executed)
    return decision


def ai_loop():
    """Background loop that periodically asks Ollama what to do."""
    # Small delay so the serial thread has a chance to populate readings first.
    time.sleep(5)
    while True:
        try:
            with ai_lock:
                enabled = ai_state['enabled']
            if enabled:
                run_single_analysis()
        except Exception as e:
            # Never let the AI loop crash the process.
            print(f"[ai_loop] error: {e}")
        time.sleep(AI_INTERVAL_SECONDS)

# --- Background Thread for Arduino Communication ---
def read_from_arduino():
    """
    Reads data from the Arduino in a separate thread to avoid blocking the web server.
    """
    global sensor_data
    while True:
        ser = None
        try:
            # Set ARDUINO_PORT env variable to override (e.g. set ARDUINO_PORT=COM5)
            arduino_port = os.environ.get('ARDUINO_PORT', 'COM7')
            ser = serial.Serial(arduino_port, 9600, timeout=2)
            print("Arduino connected.")
            with data_lock:
                sensor_data['error'] = None

            while True:
                # Drain any pending commands before blocking on readline
                try:
                    while True:
                        cmd = command_queue.get_nowait()
                        ser.write(cmd.encode('utf-8'))
                        ser.flush()
                except queue.Empty:
                    pass

                try:
                    line = ser.readline().decode('utf-8').strip()
                except UnicodeDecodeError:
                    continue  # Skip malformed bytes from Arduino

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
                elif line.startswith("SLED:"):
                    status = line.split(':', 1)[1].strip().upper()
                    if status in ('ON', 'OFF'):
                        with data_lock:
                            sensor_data['slave_led_status'] = status
                        print(f"Slave LED status updated: {status}")
                elif line.startswith("NFC:UID="):
                    uid = line.split('=', 1)[1].strip().upper()
                    if uid:
                        matched = _lookup_tag(uid)
                        with nfc_lock:
                            nfc_state['last_uid'] = uid
                            nfc_state['last_seen_at'] = datetime.now().isoformat(timespec='seconds')
                            nfc_state['matched_name'] = matched
                        print(f"NFC tag seen: {uid} -> {matched or 'unknown'}")
                elif line.startswith("POT:"):
                    parts = line.split(':')
                    if len(parts) == 2 and parts[1].strip().lstrip('-').isdigit():
                        pot = parts[1].strip()
                        with data_lock:
                            sensor_data['pot_value'] = pot
                        print(f"Pot value: {pot}")
                elif line:
                    print(f"[Arduino] {line}")

        except serial.SerialException as e:
            print(f"Error: {e}. Is the Arduino connected?")
            with data_lock:
                sensor_data['error'] = "Arduino not connected. Retrying..."
                sensor_data['temperature'] = 'N/A'
                sensor_data['humidity'] = 'N/A'
                sensor_data['led_status'] = 'N/A'
                sensor_data['slave_led_status'] = 'N/A'
                sensor_data['pot_value'] = 'N/A'
        finally:
            if ser and ser.is_open:
                ser.close()
        time.sleep(5)  # Wait 5 seconds before trying to reconnect

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

@app.route('/led', methods=['POST'])
def set_led():
    action = request.json.get('action', '')
    if action == 'on':
        command_queue.put('A')
        return jsonify({'status': 'ok', 'command': 'A'})
    elif action == 'off':
        command_queue.put('S')
        return jsonify({'status': 'ok', 'command': 'S'})
    return jsonify({'status': 'error', 'message': 'Invalid action'}), 400

@app.route('/ai/state')
def ai_get_state():
    with ai_lock:
        return jsonify({
            'enabled': ai_state['enabled'],
            'last_run': ai_state['last_run'],
            'last_decision': ai_state['last_decision'],
            'log': list(reversed(ai_state['log'])),  # newest first
            'interval_seconds': AI_INTERVAL_SECONDS,
        })

@app.route('/ai/analyze', methods=['POST'])
def ai_analyze_now():
    decision = run_single_analysis()
    with ai_lock:
        return jsonify({
            'decision': decision,
            'last_run': ai_state['last_run'],
        })

@app.route('/face/users', methods=['GET'])
def face_users():
    """Return the list of enrolled user names (no descriptors)."""
    with face_lock:
        users = _load_face_db()
    return jsonify({'users': [u.get('name', '') for u in users]})


@app.route('/face/enroll', methods=['POST'])
def face_enroll():
    """
    Body: {"name": "...", "descriptor": [128 floats]}
    Stores or replaces the descriptor for that name.
    """
    payload = request.get_json(silent=True) or {}
    name = (payload.get('name') or '').strip()
    descriptor = payload.get('descriptor')
    if not name:
        return jsonify({'status': 'error', 'message': 'Name is required'}), 400
    if not isinstance(descriptor, list) or len(descriptor) != 128:
        return jsonify({'status': 'error', 'message': 'Descriptor must be a 128-float array'}), 400
    try:
        descriptor = [float(x) for x in descriptor]
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'message': 'Descriptor values must be numbers'}), 400

    with face_lock:
        users = _load_face_db()
        # Replace existing entry for this name (case-insensitive) or append.
        replaced = False
        for u in users:
            if u.get('name', '').lower() == name.lower():
                u['descriptor'] = descriptor
                u['name'] = name
                replaced = True
                break
        if not replaced:
            users.append({'name': name, 'descriptor': descriptor})
        _save_face_db(users)

    return jsonify({'status': 'ok', 'name': name, 'replaced': replaced, 'count': len(users)})


@app.route('/face/identify', methods=['POST'])
def face_identify():
    """
    Body: {"descriptor": [128 floats]}
    Returns the closest enrolled user if distance <= threshold.
    """
    payload = request.get_json(silent=True) or {}
    descriptor = payload.get('descriptor')
    if not isinstance(descriptor, list) or len(descriptor) != 128:
        return jsonify({'matched': False, 'reason': 'Invalid descriptor'}), 400

    with face_lock:
        users = _load_face_db()

    if not users:
        return jsonify({'matched': False, 'reason': 'No enrolled users', 'enrolled': 0})

    best_name = None
    best_dist = float('inf')
    for u in users:
        d = _euclidean(descriptor, u.get('descriptor', []))
        if d < best_dist:
            best_dist = d
            best_name = u.get('name', '')

    matched = best_dist <= FACE_MATCH_THRESHOLD
    return jsonify({
        'matched': matched,
        'name': best_name if matched else None,
        'distance': round(best_dist, 4),
        'threshold': FACE_MATCH_THRESHOLD,
        'enrolled': len(users),
    })


@app.route('/face/users/<name>', methods=['DELETE'])
def face_delete_user(name):
    target = (name or '').strip().lower()
    if not target:
        return jsonify({'status': 'error'}), 400
    with face_lock:
        users = _load_face_db()
        before = len(users)
        users = [u for u in users if u.get('name', '').lower() != target]
        _save_face_db(users)
    return jsonify({'status': 'ok', 'removed': before - len(users)})


@app.route('/nfc/state', methods=['GET'])
def nfc_get_state():
    """Latest tag seen by the master Arduino, plus whether it's enrolled."""
    with nfc_lock:
        return jsonify(dict(nfc_state))


@app.route('/nfc/users', methods=['GET'])
def nfc_users():
    """Return enrolled tag-user names (no UIDs leak to clients)."""
    tags = _load_tag_db()
    return jsonify({'users': [t.get('name', '') for t in tags]})


@app.route('/nfc/enroll', methods=['POST'])
def nfc_enroll():
    """
    Body: {"name": "...", "uid": "04A1B2C3"}
    Stores or replaces the tag for that name. Re-evaluates nfc_state so the
    modal sees the new match immediately on the next poll.
    """
    payload = request.get_json(silent=True) or {}
    name = (payload.get('name') or '').strip()
    uid = (payload.get('uid') or '').strip().upper()
    if not name or not uid:
        return jsonify({'status': 'error', 'message': 'name and uid are required'}), 400

    tags = _load_tag_db()
    replaced = False
    for t in tags:
        if t.get('uid', '').upper() == uid:
            t['name'] = name
            replaced = True
            break
        if t.get('name', '').lower() == name.lower():
            t['uid'] = uid
            replaced = True
            break
    if not replaced:
        tags.append({'name': name, 'uid': uid})
    _save_tag_db(tags)

    # Refresh the matched_name on the current state so the polling modal
    # sees the new association without waiting for another tap.
    with nfc_lock:
        if nfc_state['last_uid'] == uid:
            nfc_state['matched_name'] = name

    return jsonify({'status': 'ok', 'name': name, 'uid': uid, 'replaced': replaced, 'count': len(tags)})


@app.route('/nfc/users/<name>', methods=['DELETE'])
def nfc_delete_user(name):
    target = (name or '').strip().lower()
    if not target:
        return jsonify({'status': 'error'}), 400
    tags = _load_tag_db()
    before = len(tags)
    tags = [t for t in tags if t.get('name', '').lower() != target]
    _save_tag_db(tags)
    return jsonify({'status': 'ok', 'removed': before - len(tags)})


@app.route('/ai/voice', methods=['POST'])
def ai_voice():
    """
    Receive a transcript from the dashboard's push-to-talk button,
    have Ollama interpret it, execute side effects (LED commands),
    and return a spoken reply for the browser to read out loud.
    """
    payload = request.get_json(silent=True) or {}
    transcript = (payload.get('text') or '').strip()
    user_name = (payload.get('user') or '').strip() or None
    if not transcript:
        return jsonify({'action': 'none', 'speech': "I didn't hear anything.", 'transcript': ''}), 400

    snapshot = _snapshot_sensors()
    if snapshot.get('error'):
        return jsonify({
            'action': 'none',
            'speech': 'The Arduino is not connected, so I cannot read the sensors right now.',
            'transcript': transcript,
        })

    decision = ollama_voice_command(transcript, snapshot, user_name)
    action = decision.get('action', 'none')
    executed = False

    led_status = str(snapshot.get('led_status', '')).strip().upper()
    if action == 'led_on' and led_status != 'ON':
        command_queue.put('A')
        executed = True
    elif action == 'led_off' and led_status != 'OFF':
        command_queue.put('S')
        executed = True
    # report_* and none have no side effects.

    # Log the voice interaction in the AI activity log too, so it shows up
    # alongside the autonomous decisions.
    _record_ai_run(
        snapshot,
        {'action': f"voice:{action}", 'reason': f'"{transcript}" -> {decision.get("speech", "")}'},
        executed,
    )

    return jsonify({
        'action': action,
        'speech': decision.get('speech', ''),
        'transcript': transcript,
        'executed': executed,
    })

@app.route('/ai/toggle', methods=['POST'])
def ai_toggle():
    with ai_lock:
        ai_state['enabled'] = not ai_state['enabled']
        return jsonify({'enabled': ai_state['enabled']})

if __name__ == '__main__':
    # Start the background thread that reads from the Arduino
    arduino_thread = threading.Thread(target=read_from_arduino, daemon=True)
    arduino_thread.start()

    # Start the AI analysis loop
    ai_thread = threading.Thread(target=ai_loop, daemon=True)
    ai_thread.start()

    # Start the Flask web server
    # Use host='0.0.0.0' to make it accessible from other devices on your network
    app.run(host='0.0.0.0', port=5000, debug=False)
