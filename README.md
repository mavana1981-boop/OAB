# Diário de Estudos — OAB (Flask)

Dashboard estatístico do caderno de questões OAB (matéria, assunto, ano,
gabarito), servido por Flask e pronto para deploy no Railway.

## Estrutura

```
app.py              # servidor Flask
data.json            # base atual: 400 questões
build_data.py        # script fonte — editar `rows` aqui para add/alterar questões
templates/index.html # dashboard (mesma UI da versão estática, agora via Jinja2)
requirements.txt
Procfile              # comando de start (gunicorn) para o Railway
runtime.txt
```

## Rodar localmente

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
# abre em http://localhost:5000
```

## Deploy no Railway

1. Suba esta pasta para um repo no GitHub (ou use `railway up` direto da CLI).
2. No Railway: New Project → Deploy from GitHub repo.
3. O Railway detecta Python automaticamente via `requirements.txt` +
   `Procfile` (Nixpacks). Não precisa configurar nada além da variável
   `PORT`, que o próprio Railway injeta.
4. Deploy. A URL pública vai servir o dashboard na rota `/`.

Rotas disponíveis:
- `GET /` — dashboard completo (HTML)
- `GET /api/questoes` — JSON de todas as questões, com filtros opcionais
  via querystring: `?materia=Penal&ano=2025&gabarito=A&busca=furto`
- `GET /healthz` — healthcheck simples (`{"status":"ok","questoes":400}`)
- `GET /importar` — formulário para subir um novo PDF
- `POST /importar` — processa o PDF (ver seção abaixo)

## Adicionar mais questões — via upload de PDF (recomendado)

A rota `/importar` deixa você subir um novo PDF do TecConcursos direto
pelo navegador. O Claude lê o PDF nativamente (sem OCR/parsing manual),
extrai matéria/assunto/ano/gabarito de cada questão, e o servidor
**descarta automaticamente qualquer questão cujo número (qid, extraído
da URL do TecConcursos) já exista em `data.json`** — então reimportar o
mesmo PDF, ou um PDF com questões repetidas, nunca duplica linhas.

### Configuração necessária no Railway

Em **Variables**, adicione:

| Variável            | Descrição                                                             |
|---------------------|------------------------------------------------------------------------|
| `ANTHROPIC_API_KEY` | Sua chave da API da Anthropic (console.anthropic.com → API Keys)      |
| `IMPORT_TOKEN`      | Uma senha à sua escolha, só para proteger a rota `/importar`          |

Sem `ANTHROPIC_API_KEY`, a extração falha com um erro explicativo.
Sem `IMPORT_TOKEN`, a rota fica bloqueada por padrão (para ninguém além
de você conseguir escrever na base pelo link público do Railway).

### Como usar

1. Acesse `https://SEU-APP.up.railway.app/importar`.
2. Selecione o PDF novo e digite a chave (`IMPORT_TOKEN`).
3. Envie. A tela de resultado mostra quantas questões foram lidas,
   quantas foram **adicionadas** e quantas foram **duplicadas e
   ignoradas** (com o assunto de cada uma, para conferência).
4. `data.json` já fica atualizado no servidor — o dashboard em `/`
   reflete o novo total imediatamente, sem precisar reiniciar o app.

> Atenção: no Railway, o sistema de arquivos é efêmero em alguns planos
> (o container pode reiniciar e perder gravações locais). Se isso
> acontecer com sua conta, depois de importar baixe o `data.json`
> atualizado (ex. via `railway run cat data.json > data.json` ou um
> volume persistente do Railway) e faça commit dele no repositório para
> não perder o histórico entre deploys.

## Adicionar mais questões — manualmente (alternativa)

1. Abra `build_data.py`.
2. Acrescente novas tuplas em `rows` no formato:
   `(num, ano, materia, assunto, gabarito, qid)`
3. Rode:
   ```bash
   python3 build_data.py
   ```
   Isso regenera `data.json` com todas as questões (antigas + novas).
4. Reinicie o app localmente (ou faça novo deploy no Railway).

Não precisa mexer em `app.py` nem em `templates/index.html` para
adicionar questões — só em `build_data.py`, ou usar a rota `/importar`.
