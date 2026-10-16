import json
import os
from pathlib import Path
from datetime import datetime, timezone

import requests

API_URL = "https://syklo-orderbook.ddns.net/book"

USDC = "USDC:ALL:SYKLO"
METODO_VES = "VES:VE:PF"

STATE_FILE = Path("state.json")
WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")

session = requests.Session()
session.headers.update({"Accept": "application/json"})


def cargar_estado():
    if not STATE_FILE.exists():
        return {}

    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def guardar_estado(estado):
    STATE_FILE.write_text(
        json.dumps(estado, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def obtener_precio(enviar, recibir, lado):
    respuesta = session.get(
        API_URL,
        params={
            "send_pms": enviar,
            "receive_pms": recibir,
        },
        timeout=25,
    )
    respuesta.raise_for_status()
    datos = respuesta.json()

    clave = f"{lado}:{METODO_VES}"
    oferta = datos.get(clave)

    if not oferta:
        print(f"Sin ofertas disponibles: {clave}")
        return None

    precios = oferta.get("r_price", [])
    rec = oferta.get("reciprocal", [])
    validos = []

    for i, valor in enumerate(precios):
        try:
            precio = float(valor)

            if i < len(rec) and rec[i]:
                if precio == 0:
                    continue
                precio = 1 / precio

            if precio > 0:
                validos.append(precio)
        except (TypeError, ValueError, ZeroDivisionError):
            continue

    if not validos:
        return None

    return max(validos) if lado == "BID" else min(validos)


def enviar_alerta(mensaje):
    if not WEBHOOK:
        print("Falta configurar el secreto DISCORD_WEBHOOK_URL.")
        return False

    try:
        respuesta = session.post(
            WEBHOOK,
            json={"content": mensaje},
            timeout=20,
        )
        respuesta.raise_for_status()
        print("Alerta enviada a Discord.")
        return True
    except requests.RequestException as error:
        print(f"Error enviando a Discord: {error}")
        return False


def main():
    estado = cargar_estado()

    mercados = [
        (
            "USDC → VES (BID)",
            USDC,
            METODO_VES,
            "BID",
        ),
        (
            "VES → USDC (ASK)",
            METODO_VES,
            USDC,
            "ASK",
        ),
    ]

    for nombre, enviar, recibir, lado in mercados:
        try:
            precio = obtener_precio(enviar, recibir, lado)
        except (requests.RequestException, ValueError) as error:
            print(f"Error consultando {nombre}: {error}")
            continue

        if precio is None:
            continue

        clave = nombre
        anterior = estado.get(clave)

        print(f"{nombre}: {precio:.4f} VES/USDC")

        if anterior is not None:
            anterior = float(anterior)
            variacion = (precio - anterior) / anterior * 100
            direccion = "SUBIÓ 📈" if variacion > 0 else "BAJÓ 📉" if variacion < 0 else "SIN CAMBIOS 🔄"
            cambio_str = f"{direccion} {abs(variacion):.2f}%"
        else:
            variacion = 0.0
            cambio_str = "Primer registro 🚀"

        mensaje = (
            f"🔔 **Reporte Syklo USDC/VES**\n"
            f"**Método:** {METODO_VES}\n"
            f"**Mercado:** {nombre}\n"
            f"**Precio actual:** `{precio:.4f}` VES/USDC\n"
            f"**Estado:** {cambio_str}\n"
            f"**Hora UTC:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}"
        )

        if enviar_alerta(mensaje):
            estado[clave] = precio

    guardar_estado(estado)
    print("Estado actualizado y notificaciones enviadas.")


if __name__ == "__main__":
    main()
