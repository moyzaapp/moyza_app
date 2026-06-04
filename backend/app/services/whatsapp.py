import requests
import time
import random


EVOLUTION_URL_SENDMEDIA = "http://evomoyza.duckdns.org/message/sendMedia/jobany"
EVOLUTION_URL_SENDPRESENCE = "http://evomoyza.duckdns.org/message/sendPresence/jobany"
API_KEY = "MOYZA_SUPER_KEY"

def human_delay():
    time.sleep(random.uniform(2, 6))


def send_report(phone, file_url, caption):

    payload = {
        "number": phone,
        "mediatype": "document",
        "media": file_url,
        "fileName": "reporte.pdf",
        "caption": caption
    }

    headers = {
        "Content-Type": "application/json",
        "apikey": API_KEY
    }

    # simular escribir mensaje
    try:
        response = requests.post(
            EVOLUTION_URL_SENDPRESENCE,
            json={"number": phone, "delay": 4500, "presence": "composing"},
            headers=headers
        )
    except:
        pass

    #delay humano
    human_delay()

    # enviar el mensaje con el archivo
    response = requests.post(
        EVOLUTION_URL_SENDMEDIA,
        json=payload,
        headers=headers
    )

    return response.json()