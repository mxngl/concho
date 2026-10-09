# Concho Discord bot (P6.6). Build context: agent/bot/.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY bot.py .
USER nobody
CMD ["python", "bot.py"]
