import os
import sys
import tempfile
from datetime import datetime
from urllib.parse import urlparse, parse_qs
import mysql.connector
from flask import Flask, request, Response, render_template_string

app = Flask(__name__)
ENV_DB_URL = os.environ.get('DATABASE_URL', '')

HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>MySQL Exporter</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body{font-family:sans-serif;padding:40px;max-width:800px;margin:0 auto}
  textarea{width:100%;font-family:monospace;font-size:13px;padding:8px;box-sizing:border-box}
  .badge{background:#e8f5e9;border:1px solid #c8e6c9;padding:8px 14px;border-radius:6px;margin-bottom:16px;font-size:14px}
  label{font-weight:bold;display:block;margin-bottom:4px}
  .mb-3{margin-bottom:16px}
  .text-muted{color:#666;font-size:12px}
  .btn{padding:10px 20px;font-size:14px;border:none;border-radius:4px;cursor:pointer;color:#fff}
  .btn-primary{background:#0d6efd}
  .btn-success{background:#198754}
  hr{margin:24px 0}
</style>
</head>
<body>
<h2>MySQL Database Exporter</h2>
{% if env_configured %}
<div class="badge">DATABASE_URL env configured</div>
{% else %}
<p class="text-muted">Paste your MySQL URL to export all tables as SQL.</p>
{% endif %}
<form method="POST" action="/export">
  <div class="mb-3">
    <label>MySQL Connection URL</label>
    <textarea name="url" rows="3" {% if env_url %}value="{{ env_url }}"{% else %}placeholder="mysql://user:pass@host:3306/db?ssl-mode=REQUIRED"{% endif %}></textarea>
    <div class="text-muted">Format: mysql://user:pass@host:port/db?ssl-ca=./ca.pem&ssl-mode=VERIFY_IDENTITY</div>
  </div>
  <div class="mb-3">
    <label>SSL CA Certificate <span class="text-muted">(paste PEM if ssl-ca is a file path)</span></label>
    <textarea name="sslCA" rows="4" placeholder="-----BEGIN CERTIFICATE-----..."></textarea>
  </div>
  <button type="submit" class="btn btn-primary">Export Database</button>
</form>
{% if env_configured %}
<hr>
<form method="POST" action="/export-env">
  <button class="btn btn-success">Export via DATABASE_URL env</button>
</form>
{% endif %}
</body></html>'''


def parse_mysql_url(url):
    parsed = urlparse(url)
    if parsed.scheme != 'mysql':
        return None
    db = parsed.path.lstrip('/')
    qs = parse_qs(parsed.query)
    ssl_ca = (qs.get('ssl-ca') or qs.get('sslCA') or [''])[0]
    ssl_mode = (qs.get('ssl-mode') or qs.get('sslmode') or [''])[0]
    return {
        'host': parsed.hostname,
        'port': parsed.port or 3306,
        'user': parsed.username or '',
        'password': parsed.password or '',
        'database': db,
        'sslCA': ssl_ca,
        'sslMode': ssl_mode,
    }


def resolve_ca(ca):
    if not ca:
        return None
    if '-----BEGIN CERTIFICATE-----' in ca:
        return ca
    ca_path = os.path.join(os.path.dirname(__file__), ca)
    if os.path.exists(ca_path):
        with open(ca_path) as f:
            return f.read()
    return None


def write_ca_temp(pem_content):
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.pem', delete=False)
    tmp.write(pem_content)
    tmp.close()
    return tmp.name


def safe(v):
    if v is None:
        return 'NULL'
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v).replace('\\', '\\\\').replace("'", "\\'")
    return f"'{s}'"


def do_export(parsed, ssl_ca_form):
    config = {
        'host': parsed['host'],
        'port': parsed['port'],
        'user': parsed['user'],
        'password': parsed['password'],
        'database': parsed['database'],
        'connect_timeout': 30,
    }
    ca_pem = ssl_ca_form or resolve_ca(parsed['sslCA'])
    ca_temp_file = None
    if ca_pem:
        ca_temp_file = write_ca_temp(ca_pem)
        config['ssl_ca'] = ca_temp_file
    ssl_mode = parsed['sslMode']
    if ssl_mode and ssl_mode in ('VERIFY_IDENTITY', 'VERIFY_CA'):
        config['ssl_verify_cert'] = True
        config['ssl_verify_identity'] = (ssl_mode == 'VERIFY_IDENTITY')

    conn = None
    try:
        conn = mysql.connector.connect(**config)
        cursor = conn.cursor()
        cursor.execute('SHOW TABLES')
        tables = cursor.fetchall()

        output = f'-- MySQL Export - {parsed["database"]}\n'
        output += f'-- Host: {parsed["host"]}:{parsed["port"]}\n'
        output += f'-- Generated: {datetime.now().isoformat()}\n\n'
        output += f'CREATE DATABASE IF NOT EXISTS `{parsed["database"]}`;\n'
        output += f'USE `{parsed["database"]}`;\n\n'

        for (table,) in tables:
            if table.startswith('knex_'):
                continue
            cursor.execute(f'SHOW CREATE TABLE `{table}`')
            create_sql = cursor.fetchone()[1]
            cursor.execute(f'SELECT * FROM `{table}`')
            rows = cursor.fetchall()
            col_names = [d[0] for d in cursor.description]
            inserts = []
            for row_data in rows:
                vals = [safe(v) for v in row_data]
                inserts.append(f'INSERT INTO `{table}` VALUES ({",".join(vals)});')
            output += f'-- Table: {table}\n{create_sql};\n\n'
            output += '\n'.join(inserts) + '\n\n'

        return Response(
            output,
            mimetype='application/sql',
            headers={'Content-Disposition': f'attachment; filename="{parsed["database"]}-export.sql"'}
        )
    except Exception as e:
        return f'<h3>Error</h3><pre>{type(e).__name__}: {e}</pre><a href="/">Back</a>', 500
    finally:
        if conn:
            conn.close()
        if ca_temp_file:
            os.unlink(ca_temp_file)


@app.route('/')
def index():
    return render_template_string(HTML,
        env_configured=bool(ENV_DB_URL),
        env_url=ENV_DB_URL)


@app.route('/export', methods=['POST'])
def export():
    url = request.form.get('url', '').strip()
    ssl_ca = request.form.get('sslCA', '').strip()
    if not url:
        return '<h3>Error</h3><pre>MySQL URL is required</pre><a href="/">Back</a>'
    parsed = parse_mysql_url(url)
    if not parsed:
        return '<h3>Error</h3><pre>Invalid MySQL URL</pre><a href="/">Back</a>'
    return do_export(parsed, ssl_ca)


@app.route('/export-env', methods=['POST'])
def export_env():
    if not ENV_DB_URL:
        return '<h3>Error</h3><pre>DATABASE_URL not configured</pre><a href="/">Back</a>'
    parsed = parse_mysql_url(ENV_DB_URL)
    if not parsed:
        return '<h3>Error</h3><pre>Invalid DATABASE_URL env</pre><a href="/">Back</a>'
    return do_export(parsed, '')


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    app.run(host='0.0.0.0', port=port)
