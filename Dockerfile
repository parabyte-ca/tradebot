FROM python:3.11-slim

LABEL maintainer="parabyte-ca"
LABEL version="0.1.0"
LABEL description="tradebot — AI swing trading bot (PAPER TRADING ONLY)"

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies before copying source (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Create data directories (will be bind-mounted in production)
RUN mkdir -p /data/models

# Prometheus metrics endpoint
EXPOSE 8421

# Run the bot
CMD ["python", "-m", "bot.main"]
