# Discord bot of the Concho bundle (P6.6). Build context: agent/bot.
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && useradd --create-home --uid 10001 concho
COPY payload.py bot.py ./
USER concho
CMD ["python", "-u", "bot.py"]
