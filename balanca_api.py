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

# FUNÇÕES AUXILIARES

# Lê o arquivo JSON da balança, criando se não existir
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

# Obtém o número de série do Raspberry Pi
def get_raspberry_serial():
    try:
        serial = subprocess.check_output(
            "cat /proc/cpuinfo | grep Serial | cut -d ' ' -f 2", shell=True
        )
        return serial.decode("utf-8").strip()
    except Exception:
        return "serial_desconhecido"


IDENTIFICADOR_BALANCA = get_raspberry_serial()
#  Identificador da balança

# ROTAS
@app.route("/")
def home():
    return jsonify({"status": "ok", "mensagem": "API da balança ativa"})

# Realiza tara e salva o offset
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
        "status": "sucesso",
        "mensagem": "Tara realizada com sucesso",
        "offset": offset
    })

# Calcula automaticamente o reference_unit a partir de um peso conhecido
@app.route("/calibrar-reference", methods=["POST"])
def calibrar_reference():
    try:
        data = request.get_json()
        peso_conhecido = float(data.get("peso_conhecido", 0))
        if peso_conhecido <= 0:
            return jsonify({"status": "erro", "mensagem": "Informe um peso válido (> 0)"}), 400

        dados = carregar_dados()
        offset = dados.get("offset", 0)

        hx = HX711(5, 6)
        hx.set_offset(offset)

        # Ler o valor bruto com peso sobre a balança
        leituras = [hx.read_long() for _ in range(10)]
        media_crua = sum(leituras) / len(leituras)

        reference_unit = (media_crua - offset) / peso_conhecido
        dados["reference_unit"] = reference_unit
        salvar_dados(dados)

        return jsonify({
            "status": "sucesso",
            "mensagem": "Reference unit calibrado e salvo com sucesso",
            "reference_unit": reference_unit,
            "offset": offset
        }), 200

    except Exception as e:
        # Erro na calibração
        return jsonify({"status": "erro", "mensagem": str(e)}), 500

# Lê o peso atual usando o reference_unit calibrado
@app.route("/teste-peso", methods=["GET"])
def teste_peso():
    dados = carregar_dados()
    reference_unit = dados.get("reference_unit")
    offset = dados.get("offset", 0)

    if not reference_unit:
        return jsonify({"status": "erro", "mensagem": "Reference unit não calibrado ainda"}), 400

    hx = HX711(5, 6)
    hx.set_reference_unit(reference_unit)
    hx.set_offset(offset)

    peso = max(0, int(hx.get_weight(5)))

    return jsonify({
        "status": "sucesso",
        "peso": peso,
        "reference_unit": reference_unit,
        "offset": offset
    })


# COLETA DE PESAGEM

# Inicia ou finaliza uma coleta e envia o peso para a API
@app.route('/coleta-balanca', methods=['GET'])
def coleta_endpoint():
    try:
        acao = request.args.get("acao")
        if acao not in ["iniciar", "finalizar"]:
            return jsonify({
                "retorno": {"status": 400, "mensagem": "Parâmetro 'acao' inválido"}
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
            # Coleta iniciada

        salvar_dados(dados)

        payload = {
            "peso_atual": diferenca,
            "identificador_balanca": IDENTIFICADOR_BALANCA,
            "tipo_peso": 1
        }

        if acao == "finalizar":
            url = "https://api-pesagem-chi.vercel.app/peso-caixa"
            try:
                response = requests.post(url, json=payload, timeout=5)
                # Envio para servidor
                dados["coleta_status"] = "inativa"
                salvar_dados(dados)
                # Coleta finalizada

            except requests.RequestException as e:
                # Falha ao enviar para API
                dados["coleta_status"] = "inativa"
                salvar_dados(dados)
                # Coleta finalizada (com erro no envio)

        return jsonify(payload), 200

    except Exception as e:
        # Erro na coleta
        return jsonify({
            "retorno": {
                "status": 500,
                "mensagem": "Falha ao processar coleta",
                "erro": str(e)
            }
        }), 500


# MAIN
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)