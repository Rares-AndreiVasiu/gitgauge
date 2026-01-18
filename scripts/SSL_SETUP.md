# Let's Encrypt SSL Certificate Setup for gitgauge.reuron.com

This guide explains how to set up Let's Encrypt SSL certificates for your nginx endpoints.

## Prerequisites

1. Domain `gitgauge.reuron.com` must point to this server's IP address
2. Ports 80 and 443 must be open in your firewall
3. Docker and docker-compose must be installed

## Initial Certificate Setup

### Step 1: Ensure DNS is configured

Make sure `gitgauge.reuron.com` points to this server's IP address. You can verify with:

```bash
dig gitgauge.reuron.com +short
```

### Step 2: Set your email (optional but recommended)

Edit `/home/ubuntu/gitgauge/scripts/obtain-certificate.sh` and set the `EMAIL` variable, or set the environment variable:

```bash
export CERTBOT_EMAIL="your-email@example.com"
```

### Step 3: Run the certificate obtainment script

```bash
cd /home/ubuntu/gitgauge
./scripts/obtain-certificate.sh
```

This script will:
- Check if certbot is installed and install it if needed
- Temporarily switch nginx to HTTP-only mode (if SSL config is active)
- Stop nginx temporarily
- Obtain the certificate from Let's Encrypt using standalone mode
- Set proper permissions for Docker to access certificates
- Restore the SSL nginx configuration
- Restart nginx with SSL enabled

**Note:** If nginx fails to start initially because certificates don't exist, the script will automatically handle this by using the HTTP-only configuration temporarily.

### Step 3: Verify SSL is working

Visit `https://gitgauge.reuron.com` in your browser. You should see a valid SSL certificate.

## Automatic Certificate Renewal

Let's Encrypt certificates expire after 90 days. To set up automatic renewal:

### Option 1: Add to crontab (recommended)

```bash
crontab -e
```

Add this line to run renewal check daily at 3 AM:

```
0 3 * * * /home/ubuntu/gitgauge/scripts/renew-certificate.sh >> /var/log/certbot-renewal.log 2>&1
```

### Option 2: Test renewal manually

You can test the renewal process (dry-run) with:

```bash
sudo certbot renew --dry-run --config-dir /home/ubuntu/gitgauge/certbot/conf
```

## Troubleshooting

### Certificate not found error

If nginx fails to start because certificates don't exist yet:
1. Make sure the domain DNS is pointing to this server
2. Ensure port 80 is accessible from the internet
3. Run the `obtain-certificate.sh` script

### Permission errors

If you see permission errors, ensure the certbot directories are accessible:

```bash
sudo chown -R $USER:$USER /home/ubuntu/gitgauge/certbot
sudo chmod -R 755 /home/ubuntu/gitgauge/certbot
```

### Nginx won't start

Check nginx logs:

```bash
docker-compose logs nginx
```

### Certificate renewal fails

1. Check that port 80 is still accessible
2. Verify the domain still points to this server
3. Check certbot logs: `sudo cat /home/ubuntu/gitgauge/certbot/conf/logs/letsencrypt.log`

## File Structure

```
gitgauge/
├── certbot/
│   ├── conf/          # Certbot configuration and certificates
│   └── www/           # Webroot for HTTP-01 challenges
├── nginx/
│   └── nginx.conf     # Nginx configuration with SSL
└── scripts/
    ├── obtain-certificate.sh    # Initial certificate setup
    └── renew-certificate.sh     # Certificate renewal
```

## Notes

- Certificates are stored in `/home/ubuntu/gitgauge/certbot/conf/live/gitgauge.reuron.com/`
- The nginx container mounts these certificates at `/etc/letsencrypt/` inside the container
- HTTP traffic is automatically redirected to HTTPS
- The certificate will be automatically renewed if the cron job is set up

