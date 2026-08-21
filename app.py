import json
import os

from flask import Flask, jsonify, render_template, request

import db
from importer import ImportError_, extract_questions_from_pdf

app = Flask(__name__)

# Chave simples para proteger a rota de importação (que escreve no banco).
# Defina IMPORT_TOKEN nas variáveis de ambiente do Railway; sem ela
# configurada, a importação fica bloqueada por segurança.
IMPORT_TOKEN = os.environ.get("IMPORT_TOKEN")


def db_error_or_none():
    """Garante schema criado + seed aplicado (uma vez por processo) e
    devolve uma mensagem amigável se o banco não estiver configurado,
    em vez de estourar um 500 cru."""
    try:
        db.ensure_ready()
        return None
    except Exception as e:
        return str(e)


@app.route("/")
def index():
    err = db_error_or_none()
    if err:
        return f"<pre>Erro de conexão com o banco de dados:\n\n{err}</pre>", 500
    data = db.fetch_all()
    return render_template("index.html", data_json=json.dumps(data, ensure_ascii=False))


@app.route("/api/questoes")
def api_questoes():
    err = db_error_or_none()
    if err:
        return jsonify({"error": err}), 500

    materia = request.args.get("materia") or None
    ano = request.args.get("ano") or None
    gabarito = request.args.get("gabarito") or None
    busca = request.args.get("busca") or None

    data = db.fetch_filtered(materia=materia, ano=ano, gabarito=gabarito, busca=busca)
    return jsonify({"count": len(data), "questoes": data})


@app.route("/healthz")
def healthz():
    err = db_error_or_none()
    if err:
        return {"status": "error", "detail": err}, 500
    return {"status": "ok", "questoes": db.count()}


@app.route("/importar", methods=["GET"])
def importar_form():
    err = db_error_or_none()
    total = db.count() if not err else 0
    return render_template(
        "importar.html",
        token_configured=bool(IMPORT_TOKEN),
        total_atual=total,
        db_error=err,
    )


@app.route("/importar", methods=["POST"])
def importar_pdf():
    err = db_error_or_none()
    if err:
        return render_template(
            "importar_resultado.html",
            erro=f"Erro de conexão com o banco de dados: {err}",
        ), 500

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

    items = [
        {**it, "url": f"https://www.tecconcursos.com.br/questoes/{it['qid']}"}
        for it in raw_items
    ]
    added, duplicates = db.insert_new_questions(items)

    return render_template(
        "importar_resultado.html",
        parsed=len(raw_items),
        added=added,
        duplicates=duplicates,
        total_atual=db.count(),
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
