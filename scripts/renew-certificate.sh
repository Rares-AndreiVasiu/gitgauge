#!/bin/bash

# Script to renew Let's Encrypt certificate for gitgauge.reuron.com
# This should be run via cron for automatic renewal

set -e

DOMAIN="gitgauge.reuron.com"
CERTBOT_DIR="/home/ubuntu/gitgauge/certbot"
COMPOSE_FILE="/home/ubuntu/gitgauge/docker-compose.yml"

echo "Checking certificate renewal for $DOMAIN..."

# Check if certbot is installed
if ! command -v certbot &> /dev/null; then
    echo "Error: certbot is not installed"
    exit 1
fi

# Renew certificate using standalone mode
echo "Attempting to renew certificate..."
sudo certbot renew \
    --config-dir "$CERTBOT_DIR/conf" \
    --work-dir "$CERTBOT_DIR/conf/work" \
    --logs-dir "$CERTBOT_DIR/conf/logs" \
    --standalone \
    --non-interactive

# Fix permissions
sudo chown -R $USER:$USER "$CERTBOT_DIR/conf"
sudo chmod -R 755 "$CERTBOT_DIR/conf"

# Reload nginx to use new certificate
echo "Reloading nginx container..."
docker-compose -f "$COMPOSE_FILE" exec -T nginx nginx -s reload || \
    docker-compose -f "$COMPOSE_FILE" restart nginx

echo "Certificate renewal completed!"

