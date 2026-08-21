"""
Camada de persistência em PostgreSQL.

Substitui o data.json como fonte de verdade em produção — o Railway pode
reiniciar/recriar o container a qualquer momento, então qualquer coisa
gravada só no filesystem local pode ser perdida. Com Postgres, os dados
sobrevivem a redeploys, reinícios e escalonamento.

`data.json` continua no repositório, mas agora só é usado como massa de
dados inicial (seed): na primeira vez que o app roda contra um banco
vazio, ele importa as 400 questões de lá. Depois disso, todas as leituras
e escritas acontecem direto no Postgres.
"""

import json
import os
import re
from pathlib import Path

import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get("DATABASE_URL")
SEED_PATH = Path(__file__).parent / "data.json"

_ready = False


def get_conn():
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL não configurada. Adicione um plugin PostgreSQL "
            "ao projeto no Railway (New → Database → PostgreSQL) — a "
            "variável é injetada automaticamente."
        )
    return psycopg2.connect(DATABASE_URL)


def _qid_from_url(url):
    m = re.search(r"/questoes/(\d+)", url)
    return int(m.group(1)) if m else None


def init_db():
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS questoes (
                        id INTEGER PRIMARY KEY,
                        ano INTEGER NOT NULL,
                        materia TEXT NOT NULL,
                        assunto TEXT NOT NULL,
                        gabarito TEXT NOT NULL,
                        qid BIGINT UNIQUE NOT NULL,
                        url TEXT NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS import_jobs (
                        id SERIAL PRIMARY KEY,
                        status TEXT NOT NULL DEFAULT 'processing',
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        parsed INTEGER,
                        added JSONB,
                        duplicates JSONB,
                        error TEXT,
                        total_atual INTEGER
                    )
                    """
                )
    finally:
        conn.close()


def seed_if_empty():
    """Popula a tabela com data.json na primeira execução (tabela vazia).
    Idempotente: se já houver dados, não faz nada."""
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM questoes")
                if cur.fetchone()[0] > 0:
                    return False
                if not SEED_PATH.exists():
                    return False
                seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
                skipped = []
                for d in seed:
                    qid = _qid_from_url(d["url"])
                    if qid is None:
                        continue
                    cur.execute(
                        """
                        INSERT INTO questoes (id, ano, materia, assunto, gabarito, qid, url)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (qid) DO NOTHING
                        """,
                        (d["id"], d["ano"], d["materia"], d["assunto"], d["gabarito"], qid, d["url"]),
                    )
                    if cur.rowcount == 0:
                        skipped.append(d["id"])
                if skipped:
                    # data.json tinha qid repetido entre essas linhas (erro
                    # de captura anterior) — a segunda ocorrência foi
                    # ignorada para não travar o seed. Vale conferir e
                    # corrigir o qid correto depois via /importar ou SQL direto.
                    print(f"[seed] questões ignoradas por qid duplicado em data.json: {skipped}")
        return True
    finally:
        conn.close()


def ensure_ready():
    """Garante schema criado + seed aplicado. Roda só uma vez por processo
    (worker do gunicorn); é seguro chamar em toda request."""
    global _ready
    if _ready:
        return
    init_db()
    seed_if_empty()
    _ready = True


def count():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM questoes")
            return cur.fetchone()[0]
    finally:
        conn.close()


def fetch_all():
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, ano, materia, assunto, gabarito, url FROM questoes ORDER BY id"
            )
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def fetch_filtered(materia=None, ano=None, gabarito=None, busca=None):
    clauses = []
    params = []
    if materia:
        clauses.append("materia = %s")
        params.append(materia)
    if ano:
        clauses.append("ano = %s")
        params.append(ano)
    if gabarito:
        clauses.append("gabarito = %s")
        params.append(gabarito)
    if busca:
        clauses.append("assunto ILIKE %s")
        params.append(f"%{busca}%")

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    query = f"SELECT id, ano, materia, assunto, gabarito, url FROM questoes {where} ORDER BY id"

    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params)
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def insert_new_questions(items):
    """items: lista de dicts com ano, materia, assunto, gabarito, qid, url
    (sem 'id' — é atribuído aqui, continuando a numeração existente).

    Usa INSERT ... ON CONFLICT (qid) DO NOTHING dentro de uma única
    transação, o que cobre tanto duplicatas contra o banco quanto
    duplicatas dentro do próprio lote sendo importado (uma vez inserida,
    a linha já é visível para os próximos INSERTs da mesma transação).

    Retorna (added, duplicates).
    """
    added = []
    duplicates = []
    conn = get_conn()
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT COALESCE(MAX(id), 0) AS max_id FROM questoes")
                next_id = cur.fetchone()["max_id"] + 1

                for item in items:
                    cur.execute(
                        """
                        INSERT INTO questoes (id, ano, materia, assunto, gabarito, qid, url)
                        VALUES (%(id)s, %(ano)s, %(materia)s, %(assunto)s, %(gabarito)s, %(qid)s, %(url)s)
                        ON CONFLICT (qid) DO NOTHING
                        RETURNING id, ano, materia, assunto, gabarito, qid, url
                        """,
                        {**item, "id": next_id},
                    )
                    row = cur.fetchone()
                    if row:
                        added.append(dict(row))
                        next_id += 1
                    else:
                        duplicates.append(item)
    finally:
        conn.close()
    return added, duplicates


# --- Jobs de importação em segundo plano ---------------------------------
#
# A extração via Claude + gravação no banco pode levar bem mais tempo do
# que o proxy do Railway tolera numa única requisição HTTP (o erro
# "upstream error" no navegador é exatamente isso: o proxy desiste da
# conexão antes da resposta voltar, mesmo com o servidor ainda
# processando). Por isso o POST /importar só cria um "job" aqui e devolve
# na hora; o processamento de verdade roda numa thread em segundo plano,
# e a página de status faz polling até o job terminar.


def create_job():
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO import_jobs (status) VALUES ('processing') RETURNING id"
                )
                return cur.fetchone()[0]
    finally:
        conn.close()


def set_job_error(job_id, message):
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE import_jobs SET status = 'error', error = %s WHERE id = %s",
                    (message, job_id),
                )
    finally:
        conn.close()


def set_job_done(job_id, parsed, added, duplicates, total_atual):
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE import_jobs
                    SET status = 'done', parsed = %s, added = %s,
                        duplicates = %s, total_atual = %s
                    WHERE id = %s
                    """,
                    (
                        parsed,
                        psycopg2.extras.Json(added),
                        psycopg2.extras.Json(duplicates),
                        total_atual,
                        job_id,
                    ),
                )
    finally:
        conn.close()


def get_job(job_id):
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM import_jobs WHERE id = %s", (job_id,))
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()
