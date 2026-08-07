# cura-stro meteoblue Seeing-Scraper — Playwright/Chromium (multi-arch)
FROM python:3.12-slim

WORKDIR /app

# System-Libs für headless Chromium. (Playwrights '--with-deps' geht von
# Ubuntu-Paketnamen aus und scheitert auf Debian/ARM — daher die Liste
# explizit; deckt die Runtime-Abhängigkeiten von chromium/headless_shell ab.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libasound2 libpango-1.0-0 libpangocairo-1.0-0 libcairo2 \
    libxext6 libx11-6 libxcb1 libxi6 fonts-liberation fonts-freefont-ttf \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Browser NUR über Playwright installieren (passt IMMER zur gepinnten
# playwright-Version). KEIN System-Chromium via apt — das erkennt Playwright
# 1.49 nicht als seinen Browser (war die Ursache des 502).
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN playwright install chromium

COPY . .

EXPOSE 8090
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8090"]
