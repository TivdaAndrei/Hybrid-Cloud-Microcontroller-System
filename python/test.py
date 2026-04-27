import time
import random
from azure.iot.device import IoTHubDeviceClient, Message

# Lipeste aici Primary Connection String-ul copiat din Azure
CONNECTION_STRING = "cheia_iot"

def simulate_device():
    # Cream conexiunea cu dispeceratul Azure
    client = IoTHubDeviceClient.create_from_connection_string(CONNECTION_STRING)
    print("Conectare la Azure IoT Hub reusita!")

    try:
        while True:
            # Generam date false pentru senzorii tai
            temperatura = round(random.uniform(20.0, 25.0), 2)
            umiditate = round(random.uniform(40.0, 60.0), 2)
            nivel_fum = round(random.uniform(0.0, 10.0), 2) # Corelat cu senzorul de gaze

            # Formatam datele ca JSON (formatul standard pentru web)
            mesaj_json = f'{{"temperatura": {temperatura}, "umiditate": {umiditate}, "nivel_fum": {nivel_fum}}}'
            mesaj = Message(mesaj_json)

            print(f"Trimit mesaj: {mesaj_json}")
            client.send_message(mesaj)
            
            # Pauza de 5 secunde intre mesaje
            time.sleep(5) 
            
    except KeyboardInterrupt:
        print("Simulare oprita de utilizator.")
    finally:
        client.disconnect()

if __name__ == '__main__':
    simulate_device()