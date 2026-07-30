# MySQL Exporter (Python)

Export a MySQL database as SQL dump via web UI. Deployable on Stackshift.

## Deploy

1. Push repo → Stackshift builds automatically
2. Set `DATABASE_URL` env var in Stackshift dashboard
3. Open the deployed URL → click "Export via DATABASE_URL env"

## Local dev

```bash
pip install -r requirements.txt
DATABASE_URL=mysql://... python app.py
```
