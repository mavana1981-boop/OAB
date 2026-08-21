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

## Adicionar mais questões

1. Abra `build_data.py`.
2. Acrescente novas tuplas em `rows` no formato:
   `(num, ano, materia, assunto, gabarito, qid)`
3. Rode:
   ```bash
   python3 build_data.py
   ```
   Isso regenera `data.json` com todas as questões (antigas + novas).
4. Reinicie o app localmente (ou faça novo deploy no Railway) — os dados
   são lidos de `data.json` a cada request em `/`, então basta ter o
   arquivo atualizado no deploy.

Não precisa mexer em `app.py` nem em `templates/index.html` para
adicionar questões — só em `build_data.py`.
