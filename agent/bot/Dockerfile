FROM python:3.12-slim
WORKDIR /app
RUN useradd --system --no-create-home concho
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot.py .
USER concho
CMD ["python", "-u", "bot.py"]
