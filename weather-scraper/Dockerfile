# cura-stro meteoblue Seeing-Scraper — Playwright/Chromium (multi-arch)
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Browser + passende System-Libs installiert Playwright selbst — so bleibt
# der Browser IMMER zur gepinnten Playwright-Version passend (kein Drift bei
# handgepflegter Lib-Liste / neuen Chromium-Builds).
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN playwright install --with-deps chromium

COPY . .

EXPOSE 8090
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8090"]
