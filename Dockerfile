FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PORT=${PORT:-3000}
CMD ["sh", "-c", "python app.py"]
