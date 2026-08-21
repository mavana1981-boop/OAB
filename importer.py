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
- numero: o número impresso da própria questão no PDF, o dígito logo antes do \
  parêntese que abre cada bloco (ex. no bloco "501) Marco Araripe pretende..." \
  o numero é 501; em "119) Débora..." o numero é 119). É a numeração do \
  PDF de origem, não um índice que você deve inventar.
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
[{"numero": 501, "ano": 2023, "materia": "Empresarial", "assunto": "...", "gabarito": "A", "qid": 2490687}, ...]

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


def _extract_json_array(text, stop_reason=None):
    """Claude foi instruído a responder só com o array JSON, mas por
    segurança tentamos isolar o array mesmo se vier algum texto em volta.
    Também detecta o caso mais comum de falha: resposta cortada por
    limite de tokens (PDF grande demais para uma única chamada)."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()

    start = text.find("[")
    end = text.rfind("]")

    if start == -1 or end == -1:
        preview = text[:300] if text else "(resposta vazia)"
        if stop_reason == "max_tokens":
            raise ImportError_(
                "O PDF é grande demais para ser processado em uma única "
                "chamada — a resposta do Claude foi cortada antes de "
                "terminar o JSON. Tente dividir o PDF em partes menores "
                "(por exemplo, por matéria) e importe cada parte separadamente."
            )
        raise ImportError_(
            f"Claude não retornou um array JSON reconhecível. "
            f"Início da resposta: {preview}"
        )

    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as e:
        if stop_reason == "max_tokens":
            raise ImportError_(
                "O PDF é grande demais para ser processado em uma única "
                "chamada — a resposta do Claude foi cortada antes de "
                "terminar o JSON. Tente dividir o PDF em partes menores "
                "(por exemplo, por matéria) e importe cada parte separadamente."
            )
        raise ImportError_(f"JSON retornado pelo Claude está malformado: {e}")


def extract_questions_from_pdf(pdf_bytes):
    """Manda o PDF para o Claude e devolve a lista de questões extraídas,
    cada uma como dict com ano, materia, assunto, gabarito, qid."""
    client = _get_client()
    pdf_b64 = base64.b64encode(pdf_bytes).decode("utf-8")

    response = client.messages.create(
        model=MODEL,
        max_tokens=32000,
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

    # Log de diagnóstico — aparece nos logs do Railway se algo der errado,
    # sem precisar reproduzir o problema às cegas.
    print(
        f"[importer] stop_reason={response.stop_reason} "
        f"resposta_len={len(full_text)} "
        f"input_tokens={response.usage.input_tokens if response.usage else '?'} "
        f"output_tokens={response.usage.output_tokens if response.usage else '?'}"
    )

    raw_items = _extract_json_array(full_text, stop_reason=response.stop_reason)

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
        try:
            numero = int(item.get("numero"))
        except (TypeError, ValueError):
            numero = None
        cleaned.append(
            {
                "numero": numero,
                "qid": qid,
                "ano": ano,
                "materia": materia,
                "assunto": assunto,
                "gabarito": gabarito,
            }
        )
    return cleaned
