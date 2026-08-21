import json
import os
from pathlib import Path

from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

DATA_PATH = Path(__file__).parent / "data.json"


def load_data():
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
