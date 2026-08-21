import json
import os
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, url_for

from importer import ImportError_, extract_questions_from_pdf, merge_new_questions

app = Flask(__name__)

DATA_PATH = Path(__file__).parent / "data.json"

# Chave simples para proteger a rota de importação (que escreve em
# data.json). Defina IMPORT_TOKEN nas variáveis de ambiente do Railway;
# sem ela configurada, a importação fica bloqueada por segurança.
IMPORT_TOKEN = os.environ.get("IMPORT_TOKEN")


def load_data():
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_data(data):
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=0)


@app.route("/")
def index():
    data = load_data()
    return render_template("index.html", data_json=json.dumps(data, ensure_ascii=False))


@app.route("/api/questoes")
def api_questoes():
    """Optional JSON API with basic filtering, useful if you later want
    to query the dataset from another tool (e.g. a script, or a future
    mobile view) without re-parsing the embedded HTML payload."""
    data = load_data()

    materia = request.args.get("materia")
    ano = request.args.get("ano")
    gabarito = request.args.get("gabarito")
    busca = request.args.get("busca", "").lower()

    if materia:
        data = [d for d in data if d["materia"] == materia]
    if ano:
        data = [d for d in data if str(d["ano"]) == ano]
    if gabarito:
        data = [d for d in data if d["gabarito"] == gabarito]
    if busca:
        data = [d for d in data if busca in d["assunto"].lower()]

    return jsonify({"count": len(data), "questoes": data})


@app.route("/healthz")
def healthz():
    return {"status": "ok", "questoes": len(load_data())}


@app.route("/importar", methods=["GET"])
def importar_form():
    return render_template(
        "importar.html",
        token_configured=bool(IMPORT_TOKEN),
        total_atual=len(load_data()),
    )


@app.route("/importar", methods=["POST"])
def importar_pdf():
    if not IMPORT_TOKEN:
        return render_template(
            "importar_resultado.html",
            erro="A importação está desabilitada: defina a variável de "
            "ambiente IMPORT_TOKEN no Railway para habilitá-la.",
        ), 400

    token = request.form.get("token", "")
    if token != IMPORT_TOKEN:
        return render_template(
            "importar_resultado.html",
            erro="Chave de importação incorreta.",
        ), 403

    pdf_file = request.files.get("pdf")
    if not pdf_file or pdf_file.filename == "":
        return render_template(
            "importar_resultado.html",
            erro="Nenhum arquivo PDF enviado.",
        ), 400

    pdf_bytes = pdf_file.read()

    try:
        raw_items = extract_questions_from_pdf(pdf_bytes)
    except ImportError_ as e:
        return render_template("importar_resultado.html", erro=str(e)), 400
    except Exception as e:
        return render_template(
            "importar_resultado.html",
            erro=f"Falha ao processar o PDF com o Claude: {e}",
        ), 500

    existing = load_data()
    added, duplicates = merge_new_questions(existing, raw_items)

    if added:
        existing.extend(added)
        save_data(existing)

    return render_template(
        "importar_resultado.html",
        parsed=len(raw_items),
        added=added,
        duplicates=duplicates,
        total_atual=len(existing),
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
