import json
import os
import threading

from flask import Flask, jsonify, redirect, render_template, request, url_for

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

    # O processamento roda em segundo plano — a extração via Claude pode
    # levar mais tempo do que o proxy do Railway tolera numa única
    # requisição HTTP. O POST só registra o job e devolve na hora; a
    # página de status faz polling até terminar.
    job_id = db.create_job()
    thread = threading.Thread(
        target=_process_import_job, args=(job_id, pdf_bytes), daemon=True
    )
    thread.start()

    return redirect(url_for("importar_status", job_id=job_id))


def _process_import_job(job_id, pdf_bytes):
    try:
        raw_items = extract_questions_from_pdf(pdf_bytes)
    except ImportError_ as e:
        db.set_job_error(job_id, str(e))
        return
    except Exception as e:
        db.set_job_error(job_id, f"Falha ao processar o PDF com o Claude: {e}")
        return

    items = [
        {**it, "url": f"https://www.tecconcursos.com.br/questoes/{it['qid']}"}
        for it in raw_items
    ]

    try:
        added, renumbered, duplicates = db.insert_new_questions(items)
        total_atual = db.count()
    except Exception as e:
        db.set_job_error(job_id, f"Falha ao gravar as questões no banco: {e}")
        return

    db.set_job_done(job_id, len(raw_items), added, renumbered, duplicates, total_atual)


@app.route("/importar/status/<int:job_id>")
def importar_status(job_id):
    err = db_error_or_none()
    if err:
        return render_template(
            "importar_resultado.html",
            erro=f"Erro de conexão com o banco de dados: {err}",
        ), 500

    job = db.get_job(job_id)
    if not job:
        return render_template(
            "importar_resultado.html",
            erro="Job de importação não encontrado (pode ter sido de "
            "antes de um redeploy do servidor).",
        ), 404

    if job["status"] == "processing":
        return render_template("importar_processando.html", job_id=job_id)

    if job["status"] == "error":
        return render_template("importar_resultado.html", erro=job["error"])

    return render_template(
        "importar_resultado.html",
        parsed=job["parsed"],
        added=job["added"] or [],
        renumbered=job["renumbered"] or [],
        duplicates=job["duplicates"] or [],
        total_atual=job["total_atual"],
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
