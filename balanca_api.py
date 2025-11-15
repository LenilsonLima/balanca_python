from flask import Flask, jsonify, request
from hx711 import HX711
import os
import json
import time
import subprocess
import requests

app = Flask(__name__)

# Caminho do arquivo de configuração
PARAMETROS_BALANCA_PATH = "/home/pi/Desktop/balanca/parametros_balanca.json"

# ================================
# FUNÇÕES AUXILIARES
# ================================

def carregar_dados():
    if not os.path.exists(PARAMETROS_BALANCA_PATH):
        dados_iniciais = {
            "offset": 0,
            "ultimo_peso": 0,
            "coleta_status": "inativa",
            "reference_unit": None
        }
        with open(PARAMETROS_BALANCA_PATH, "w") as f:
            json.dump(dados_iniciais, f, indent=4)
        return dados_iniciais
    
    with open(PARAMETROS_BALANCA_PATH, "r") as f:
        return json.load(f)

def salvar_dados(dados):
    with open(PARAMETROS_BALANCA_PATH, "w") as f:
        json.dump(dados, f, indent=4)

def get_raspberry_serial():
    try:
        serial = subprocess.check_output(
            "cat /proc/cpuinfo | grep Serial | cut -d ' ' -f 2", shell=True
        )
        return serial.decode("utf-8").strip()
    except Exception:
        return "serial_desconhecido"

IDENTIFICADOR_BALANCA = get_raspberry_serial()

# ================================
# ROTAS
# ================================

@app.route("/")
def home():
    return jsonify({
        "retorno": {
            "status": 200,
            "mensagem": "API da balança ativa"
        },
        "registros": []
    })

# ---------------------------------
# TARA
# ---------------------------------
@app.route("/tarar-balanca", methods=["GET"])
def tarar_balanca():
    hx = HX711(5, 6)
    hx.reset()
    hx.tare()
    offset = hx.get_offset()

    dados = carregar_dados()
    dados["offset"] = offset
    dados["ultimo_peso"] = 0
    salvar_dados(dados)

    return jsonify({
        "retorno": {
            "status": 200,
            "mensagem": "Tara realizada com sucesso"
        },
        "registros": []
    })

# ---------------------------------
# CALIBRAR REFERENCE_UNIT
# ---------------------------------
@app.route("/calibrar-reference", methods=["POST"])
def calibrar_reference():
    try:
        data = request.get_json()
        peso_conhecido = float(data.get("peso_conhecido", 0))

        if peso_conhecido <= 0:
            return jsonify({
                "retorno": {
                    "status": 400,
                    "mensagem": "Informe um peso válido (> 0)"
                },
                "registros": []
            }), 400

        dados = carregar_dados()
        offset = dados.get("offset", 0)

        hx = HX711(5, 6)
        hx.set_offset(offset)

        leituras = [hx.read_long() for _ in range(10)]
        media_crua = sum(leituras) / len(leituras)

        reference_unit = (media_crua - offset) / peso_conhecido
        dados["reference_unit"] = reference_unit
        salvar_dados(dados)

        return jsonify({
            "retorno": {
                "status": 200,
                "mensagem": "Unidade de referência calibrada e salva com sucesso"
            },
            "registros": []
        }), 200

    except Exception as e:
        return jsonify({
            "retorno": {
                "status": 500,
                "mensagem": str(e)
            },
            "registros": []
        }), 500

# ---------------------------------
# COLETA DE PESAGEM
# ---------------------------------
@app.route('/coleta-balanca', methods=['GET'])
def coleta_endpoint():
    try:
        acao = request.args.get("acao")
        if acao not in ["iniciar", "finalizar"]:
            return jsonify({
                "retorno": {
                    "status": 400,
                    "mensagem": "Parâmetro 'acao' inválido"
                },
                "registros": []
            }), 400

        dados = carregar_dados()
        ultimo_peso = dados.get("ultimo_peso", 0)

        hx = HX711(5, 6)
        hx.set_reference_unit(dados.get("reference_unit", 103.33))
        hx.set_offset(dados.get("offset", 0))

        peso_lido = max(0, int(hx.get_weight(5)))
        diferenca = abs(peso_lido - ultimo_peso)
        dados["ultimo_peso"] = peso_lido

        if acao == "iniciar":
            dados["coleta_status"] = "ativa"

        salvar_dados(dados)

        payload = {
            "peso_atual": diferenca,
            "identificador_balanca": IDENTIFICADOR_BALANCA,
            "tipo_peso": 1
        }

        if acao == "finalizar":
            url = "https://api-pesagem-chi.vercel.app/peso-caixa"
            try:
                requests.post(url, json=payload, timeout=5)
            except requests.RequestException:
                pass
            
            dados["coleta_status"] = "inativa"
            salvar_dados(dados)

        return jsonify(payload), 200

    except Exception:
        return jsonify({
            "retorno": {
                "status": 500,
                "mensagem": "Falha ao processar coleta"
            },
            "registros": []
        }), 500

# MAIN
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)