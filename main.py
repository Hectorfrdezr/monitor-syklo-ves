import json
import os
from pathlib import Path
from datetime import datetime, timezone

import requests

API_URL = "https://syklo-orderbook.ddns.net/book"

USDC = "USDC:ALL:SYKLO"

# Definimos los métodos de pago de forma separada para evaluar las 4 combinaciones
METODOS_VES_LISTA = ["VES:VE:VEBN2", "VES:VE:PF"]

UMBRAL = 1.0  

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

    clave = f"{lado}:{enviar}"
    oferta = datos.get(clave)

    if not oferta:
        oferta = datos.get(f"{lado}:{USDC}") or list(datos.values())[0] if datos else None

    if not oferta:
        print(f"Sin ofertas disponibles para enviar: {enviar} | recibir: {recibir}")
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
    hubo_cambios = False

    mercados = []

    # Construimos dinámicamente los 4 escenarios de transacciones (2 métodos x 2 sentidos)
    for metodo in METODOS_VES_LISTA:
        # 1. USDC → VES (BID) usando este método
        mercados.append((
            f"USDC → VES ({metodo}) [BID]",
            USDC,
            metodo,
            "BID",
            metodo
        ))
        # 2. VES → USDC (ASK) usando este método
        mercados.append((
            f"VES ({metodo}) → USDC [ASK]",
            metodo,
            USDC,
            "ASK",
            metodo
        ))

    for nombre, enviar, recibir, lado, metodo_actual in mercados:
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

        if anterior is None:
            estado[clave] = precio
            hubo_cambios = True
            print(f"Precio inicial guardado para {nombre}: {precio:.4f}")
            continue

        anterior = float(anterior)
        variacion = (precio - anterior) / anterior * 100

        print(f"Variación desde la referencia: {variacion:+.2f}%")

        if abs(variacion) >= UMBRAL:
            direccion = "SUBIÓ 📈" if variacion > 0 else "BAJÓ 📉"

            mensaje = (
                f"🔔 **Alerta Syklo USDC/VES**\n"
                f"**Método:** {metodo_actual}\n"
                f"**Mercado:** {nombre}\n"
                f"**Cambio:** {direccion} {abs(variacion):.2f}%\n"
                f"**Precio anterior:** `{anterior:.4f}`\n"
                f"**Precio actual:** `{precio:.4f}` VES/USDC\n"
                f"**Hora UTC:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}"
            )

            if enviar_alerta(mensaje):
                estado[clave] = precio
                hubo_cambios = True
        else:
            print("No alcanza el umbral de alerta (1%).")

    if hubo_cambios:
        guardar_estado(estado)
        print("Estado actualizado.")
    else:
        print("No hay cambios significativos que guardar.")


if __name__ == "__main__":
    main()
