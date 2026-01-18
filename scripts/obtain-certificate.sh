#!/bin/bash

# Script to obtain Let's Encrypt certificate for gitgauge.reuron.com
# This script should be run on the host (not inside Docker)

set -e

DOMAIN="gitgauge.reuron.com"
EMAIL="${CERTBOT_EMAIL:-your-email@example.com}"  # Set CERTBOT_EMAIL env var or edit this
CERTBOT_DIR="/home/ubuntu/gitgauge/certbot"

echo "Obtaining Let's Encrypt certificate for $DOMAIN..."

# Check if certbot is installed
if ! command -v certbot &> /dev/null; then
    echo "certbot is not installed. Installing..."
    sudo apt-get update
    sudo apt-get install -y certbot
fi

# Ensure directories exist
mkdir -p "$CERTBOT_DIR/conf" "$CERTBOT_DIR/www"

# Check if certificates already exist
if [ -f "$CERTBOT_DIR/conf/live/$DOMAIN/fullchain.pem" ]; then
    echo "Certificate already exists. Use renew-certificate.sh to renew it."
    exit 0
fi

# Switch to HTTP-only config temporarily if SSL config is active
# This ensures nginx can run while we get certificates
NGINX_CONF="/home/ubuntu/gitgauge/nginx/nginx.conf"
NGINX_CONF_HTTP="/home/ubuntu/gitgauge/nginx/nginx.conf.http-only"
NGINX_CONF_BACKUP="$NGINX_CONF.bak"

# Check if current config uses SSL
if [ -f "$NGINX_CONF" ] && grep -q "listen 443" "$NGINX_CONF" 2>/dev/null; then
    echo "Temporarily switching to HTTP-only nginx config for certificate request..."
    if [ -f "$NGINX_CONF_HTTP" ]; then
        cp "$NGINX_CONF" "$NGINX_CONF_BACKUP" 2>/dev/null || true
        cp "$NGINX_CONF_HTTP" "$NGINX_CONF"
        # Restart nginx with HTTP-only config if it's running
        docker-compose -f /home/ubuntu/gitgauge/docker-compose.yml restart nginx 2>/dev/null || true
        sleep 2
    fi
fi

# Stop nginx container temporarily for standalone mode
echo "Stopping nginx container for certificate generation..."
docker-compose -f /home/ubuntu/gitgauge/docker-compose.yml stop nginx || true

# Obtain certificate using standalone mode
echo "Running certbot in standalone mode..."
sudo certbot certonly \
    --standalone \
    --non-interactive \
    --agree-tos \
    --email "$EMAIL" \
    -d "$DOMAIN" \
    --config-dir "$CERTBOT_DIR/conf" \
    --work-dir "$CERTBOT_DIR/conf/work" \
    --logs-dir "$CERTBOT_DIR/conf/logs"

# Fix permissions so Docker can read the certificates
echo "Setting permissions for certificate files..."
sudo chown -R $USER:$USER "$CERTBOT_DIR/conf"
sudo chmod -R 755 "$CERTBOT_DIR/conf"

# Restore SSL nginx config if we backed it up
if [ -f "$NGINX_CONF_BACKUP" ]; then
    echo "Restoring SSL nginx configuration..."
    mv "$NGINX_CONF_BACKUP" "$NGINX_CONF"
fi

# Restart nginx container with SSL config
echo "Restarting nginx container with SSL enabled..."
docker-compose -f /home/ubuntu/gitgauge/docker-compose.yml up -d nginx

echo ""
echo "Certificate obtained successfully!"
echo "Your site should now be accessible at https://$DOMAIN"
echo ""
echo "To set up automatic renewal, add the following to your crontab:"
echo "0 3 * * * /home/ubuntu/gitgauge/scripts/renew-certificate.sh"

