FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y     curl wget gnupg ca-certificates fonts-liberation libnss3 libatk-bridge2.0-0     libgtk-3-0 libdrm2 libxkbcommon0 libxcb1 libxcomposite1 libxdamage1 libxfixes3     libxrandr2 libgbm1 libasound2 libatspi2.0-0 libpangocairo-1.0-0 libpango-1.0-0     libcairo2 xvfb && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN python -m playwright install --with-deps chromium

COPY app ./app
COPY run_daily.py ./run_daily.py
COPY run_daily_refresh.py ./run_daily_refresh.py

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
