import time
import requests
from hx711 import HX711
import subprocess
import os
import json

# Caminhos
PARAMETROS_BALANCA_PATH = "/home/pi/Desktop/balanca/parametros_balanca.json"
TARA_FLAG_PATH = "/tmp/tarar_balanca.flag"

# Função para obter o serial único do Raspberry Pi
def get_raspberry_serial():
    try:
        serial = subprocess.check_output(
            "cat /proc/cpuinfo | grep Serial | cut -d ' ' -f 2", shell=True
        )
        return serial.decode("utf-8").strip()
    except Exception as e:
        print(f"[ERRO] Não foi possível obter o serial do Raspberry Pi: {e}")
        return "serial_desconhecido"

IDENTIFICADOR_BALANCA = get_raspberry_serial()
print(f"[INFO] Identificador da balança: {IDENTIFICADOR_BALANCA}")

# Inicializa o HX711
hx = HX711(5, 6)
hx.reset()
print("[DEBUG] Sensor resetado.")

# Carrega última tara e referência se existir
reference_unit = None
if os.path.exists(PARAMETROS_BALANCA_PATH):
    try:
        with open(PARAMETROS_BALANCA_PATH, "r") as f:
            data = json.load(f)
            ultima_offset = data.get("offset", 0)
            reference_unit = data.get("reference_unit")
            hx.set_offset(ultima_offset)
            if reference_unit:
                hx.set_reference_unit(reference_unit)
            print(f"[INFO] Última tara carregada: {ultima_offset}")
            print(f"[INFO] Referência carregada: {reference_unit}")
    except Exception as e:
        print(f"[ERRO] Não foi possível ler o arquivo de última tara: {e}")

print("[INFO] Balança pronta. Coloque o peso!")

# Loop principal
while True:
    try:
        # Carrega status e referência do arquivo
        coleta_status = "inativa"
        reference_unit = None
        if os.path.exists(PARAMETROS_BALANCA_PATH):
            with open(PARAMETROS_BALANCA_PATH, "r") as f:
                data = json.load(f)
                coleta_status = data.get("coleta_status", "inativa")
                reference_unit = data.get("reference_unit")

        # Se não tiver referência, pula envio
        if not reference_unit:
            print("[AVISO] Nenhuma referência encontrada, peso não será enviado.")
            time.sleep(5)
            continue

        # Define a referência antes da leitura
        hx.set_reference_unit(reference_unit)

        # Se coleta ativa, não envia peso
        if coleta_status == "ativa":
            print("[INFO] Coleta em andamento, envio de peso pausado.")
            time.sleep(5)
            continue

        # Aplica tara se flag existir
        if os.path.exists(TARA_FLAG_PATH):
            print("[DEBUG] Flag de tara detectada. Realizando tara...")
            hx.tare()
            print("[DEBUG] Tara concluída.")
            os.remove(TARA_FLAG_PATH)
            print("[DEBUG] Flag removida.")

            # Salva offset após tara
            data["offset"] = hx.get_offset()
            data["ultimo_peso"] = 0
            data["coleta_status"] = "inativa"
            with open(PARAMETROS_BALANCA_PATH, "w") as f:
                json.dump(data, f)
            print(f"[INFO] Offset salvo: {hx.get_offset()}")

        # Lê peso médio de 5 amostras
        peso = max(0, int(hx.get_weight(5)))
        print(f"[DEBUG] Peso lido: {peso}g")

        # Atualiza último peso no arquivo
        data["ultimo_peso"] = peso
        with open(PARAMETROS_BALANCA_PATH, "w") as f:
            json.dump(data, f)

        # Envia para API
        payload = {"peso_atual": peso, "identificador_balanca": IDENTIFICADOR_BALANCA}
        url = "http://10.42.0.1:5002/peso-caixa".
        try:
            response = requests.post(url, json=payload)
            print(f"[INFO] Peso enviado: {peso}g | Status: {response.status_code}")
        except requests.RequestException as req_err:
            print(f"[ERRO] Falha no envio para API: {req_err}")

        # Reinicia sensor
        hx.power_down()
        hx.power_up()
        time.sleep(10)

    except (KeyboardInterrupt, SystemExit):
        print("\n[INFO] Programa interrompido pelo usuário.")
        break

    except Exception as e:
        print(f"[ERRO] Falha geral: {e}")
        time.sleep(10)