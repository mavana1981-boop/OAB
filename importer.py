"""
Extração de questões de um PDF novo via Claude.

Dedup e persistência agora vivem em db.py (Postgres) — este módulo só
cuida de mandar o PDF pra API da Anthropic e devolver a lista bruta de
questões extraídas.
"""

import base64
import json
import os
import re

from anthropic import Anthropic

MODEL = "claude-sonnet-5"

EXTRACTION_PROMPT = """\
Você vai receber um PDF do TecConcursos com um caderno de questões da OAB \
(FGV), organizado em blocos por questão, seguido de um gabarito no final \
(formato "501)A502)A503)A..." ou similar).

Para CADA questão do PDF, extraia:
- ano: o ano da edição do exame, ex. no cabeçalho "FGV - NAC UNI OAB/OAB/2023" o ano é 2023 (inteiro)
- materia: a matéria antes do primeiro " - " na linha de matéria/assunto \
  (ex. "Direito Empresarial (Comercial)" -> use apenas "Empresarial"; \
  "Direito Processual Civil" -> "Processual Civil"; "Direito Penal" -> "Penal"; \
  "Direito Civil" -> "Civil"; "Direito Administrativo" -> "Administrativo"; \
  "Direito Ambiental" -> "Ambiental"; "Direito Previdenciário" -> "Previdenciário"; \
  "Direito Internacional Público e Privado" -> "Internacional"; \
  "Direito Notarial e Registral" -> "Notarial"; \
  "Direito Constitucional" -> "Constitucional"; "Direito do Trabalho" -> "Trabalho"; \
  "Direito Tributário" -> "Tributário"; "Ética Profissional" -> "Ética"; \
  "Direito Empresarial" -> "Empresarial". \
  Se a matéria não estiver nessa lista, use o nome curto sem o prefixo "Direito ".)
- assunto: o texto que vem depois do " - " na mesma linha (pode incluir a \
  referência de artigos entre parênteses, mantenha como está no PDF)
- gabarito: a letra da alternativa correta, lida do gabarito no final do PDF \
  (bloco "Gabarito"), pelo número da questão
- qid: o número que aparece na URL da questão, ex. \
  "www.tecconcursos.com.br/questoes/2490687" -> qid = 2490687

Responda APENAS com um array JSON válido, sem markdown, sem comentários, \
no formato:
[{"ano": 2023, "materia": "Empresarial", "assunto": "...", "gabarito": "A", "qid": 2490687}, ...]

Inclua uma entrada para cada questão do PDF. Não pule nenhuma. Não invente \
dados: se não conseguir identificar o gabarito de alguma questão com \
segurança, use "?" nesse campo em vez de chutar.
"""


class ImportError_(Exception):
    pass


def _get_client():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ImportError_(
            "ANTHROPIC_API_KEY não configurada nas variáveis de ambiente do Railway."
        )
    return Anthropic(api_key=api_key)


def _extract_json_array(text):
    """Claude foi instruído a responder só com o array JSON, mas por
    segurança tentamos isolar o array mesmo se vier algum texto em volta."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1:
        raise ImportError_("Claude não retornou um array JSON reconhecível.")
    return json.loads(text[start : end + 1])


def extract_questions_from_pdf(pdf_bytes):
    """Manda o PDF para o Claude e devolve a lista de questões extraídas,
    cada uma como dict com ano, materia, assunto, gabarito, qid."""
    client = _get_client()
    pdf_b64 = base64.b64encode(pdf_bytes).decode("utf-8")

    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_b64,
                        },
                    },
                    {"type": "text", "text": EXTRACTION_PROMPT},
                ],
            }
        ],
    )

    text_parts = [b.text for b in response.content if b.type == "text"]
    full_text = "\n".join(text_parts)
    raw_items = _extract_json_array(full_text)

    cleaned = []
    for item in raw_items:
        try:
            qid = int(item["qid"])
            ano = int(item["ano"])
            materia = str(item["materia"]).strip()
            assunto = str(item["assunto"]).strip()
            gabarito = str(item["gabarito"]).strip().upper()
        except (KeyError, TypeError, ValueError):
            continue
        cleaned.append(
            {
                "qid": qid,
                "ano": ano,
                "materia": materia,
                "assunto": assunto,
                "gabarito": gabarito,
            }
        )
    return cleaned
