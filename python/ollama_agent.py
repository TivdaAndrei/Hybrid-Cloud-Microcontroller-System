"""
Ollama smart-analysis agent for HomeOS.

Builds a prompt from a sensor snapshot, asks a local Ollama model to decide
whether the master LED should be on, off, or left alone, and returns the
parsed decision.

Decisions look like: {"action": "led_on" | "led_off" | "none", "reason": "..."}
"""

import json
import os

import requests

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "phi3:mini")
# First call loads the model into RAM, which can take 30-60s for ~4B-param models.
REQUEST_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "90"))

VALID_ACTIONS = {"led_on", "led_off", "none"}

VOICE_ACTIONS = {
    "led_on",
    "led_off",
    "report_temperature",
    "report_humidity",
    "report_status",
    "none",
}

VOICE_SYSTEM_PROMPT = """You are HomeOS, a voice assistant for a small Arduino-based smart home.
The user just spoke a command and you must decide which action fits and what to say back to them out loud.

Available actions:
- "led_on"              -> turn the master LED on
- "led_off"             -> turn the master LED off
- "report_temperature"  -> tell the user the current temperature
- "report_humidity"     -> tell the user the current humidity
- "report_status"       -> give a brief summary of all sensors
- "none"                -> the request is unclear, unrelated, or impossible

Strict rules:
1. Use ONLY the actual sensor values provided. Never invent numbers.
2. The "speech" field must be one short, natural sentence (under 25 words).
3. If the user asks to turn ON the master LED but it is already ON, set action to "none" and say so politely. Same for OFF.
4. If a sensor value is "N/A", say it is unavailable.
5. Respond ONLY with a JSON object of the exact shape: {"action": "...", "speech": "..."}.
"""


def _build_voice_user_prompt(transcript: str, snapshot: dict) -> str:
    return (
        "Current sensor readings:\n"
        f"- temperature: {snapshot.get('temperature', 'N/A')} C\n"
        f"- humidity: {snapshot.get('humidity', 'N/A')} %\n"
        f"- master LED: {snapshot.get('led_status', 'N/A')}\n"
        f"- slave LED: {snapshot.get('slave_led_status', 'N/A')} (brightness {snapshot.get('pot_value', 'N/A')}/1023)\n"
        f"\nThe user said: \"{transcript}\"\n"
        "Respond as JSON."
    )


def voice_command(transcript: str, snapshot: dict) -> dict:
    """
    Interpret a spoken command via Ollama.

    Returns {"action": <one of VOICE_ACTIONS>, "speech": <reply to read out loud>}.
    On any failure, returns a safe "none" decision with the error in the speech field.
    """
    transcript = (transcript or "").strip()
    if not transcript:
        return {"action": "none", "speech": "I didn't catch that."}

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": _build_voice_user_prompt(transcript, snapshot),
        "system": VOICE_SYSTEM_PROMPT,
        "format": "json",
        "stream": False,
        "options": {"temperature": 0.2},
    }
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        body = resp.json()
        raw = body.get("response", "").strip()
        if not raw:
            return {"action": "none", "speech": "Ollama returned an empty response."}
        decision = json.loads(raw)
    except requests.RequestException as e:
        return {"action": "none", "speech": f"Sorry, I couldn't reach the AI. {e}"}
    except json.JSONDecodeError:
        return {"action": "none", "speech": "Sorry, I couldn't understand the AI's reply."}

    action = str(decision.get("action", "none")).strip().lower()
    if action not in VOICE_ACTIONS:
        action = "none"
    speech = str(decision.get("speech", "")).strip() or "Okay."
    if len(speech) > 240:
        speech = speech[:237] + "..."
    return {"action": action, "speech": speech}

SYSTEM_PROMPT = """You are the smart-home reasoning agent for a small Arduino-based system called HomeOS.

You receive a snapshot of sensor readings and the current state of the master LED. Your job is to decide whether the master LED should be turned ON, turned OFF, or left alone.

Available actions:
- "led_on"  -> turn the master LED on
- "led_off" -> turn the master LED off
- "none"    -> do nothing

Sensor fields you may see:
- temperature: degrees Celsius from a DHT11 sensor (string, may be "N/A")
- humidity: relative humidity percent from the DHT11 (string, may be "N/A")
- led_status: current master LED state, "ON" or "OFF" or "N/A"
- pot_value: the slave PWM LED brightness, 0-1023 (string, may be "N/A")

Rules:
1. Be conservative. Only act when there is a clear reason. When in doubt, return "none".
2. Never request an action that matches the current led_status (do not turn on a LED that is already on).
3. If any required field is "N/A", prefer "none".
4. Keep "reason" short (one sentence, under 120 characters).
5. Respond ONLY with a JSON object of the exact shape: {"action": "...", "reason": "..."}.
"""


def _build_user_prompt(snapshot: dict) -> str:
    return (
        "Current sensor snapshot:\n"
        f"- temperature: {snapshot.get('temperature', 'N/A')} C\n"
        f"- humidity: {snapshot.get('humidity', 'N/A')} %\n"
        f"- led_status: {snapshot.get('led_status', 'N/A')}\n"
        f"- pot_value (slave PWM LED, 0-1023): {snapshot.get('pot_value', 'N/A')}\n"
        "\nDecide the next action and respond as JSON."
    )


def _normalize(decision: dict, snapshot: dict) -> dict:
    action = str(decision.get("action", "none")).strip().lower()
    if action not in VALID_ACTIONS:
        action = "none"

    # Don't act on a state that already matches.
    led_status = str(snapshot.get("led_status", "")).strip().upper()
    if action == "led_on" and led_status == "ON":
        action = "none"
    elif action == "led_off" and led_status == "OFF":
        action = "none"

    reason = str(decision.get("reason", "")).strip() or "No reason provided."
    if len(reason) > 200:
        reason = reason[:197] + "..."
    return {"action": action, "reason": reason}


def analyze(snapshot: dict) -> dict:
    """
    Ask the Ollama model what to do with the master LED.

    Returns a normalized decision dict. On any failure, returns
    {"action": "none", "reason": "<error>"} so callers never have to handle exceptions.
    """
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": _build_user_prompt(snapshot),
        "system": SYSTEM_PROMPT,
        "format": "json",
        "stream": False,
        "options": {"temperature": 0.2},
    }
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        body = resp.json()
        raw = body.get("response", "").strip()
        if not raw:
            return {"action": "none", "reason": "Empty response from Ollama."}
        decision = json.loads(raw)
    except requests.RequestException as e:
        return {"action": "none", "reason": f"Ollama request failed: {e}"}
    except json.JSONDecodeError as e:
        return {"action": "none", "reason": f"Could not parse model JSON: {e}"}

    return _normalize(decision, snapshot)
