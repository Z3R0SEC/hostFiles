# HostFlow — Self-Hosted Web Hosting Platform

A Flask-based shared hosting platform. Deploy PHP/HTML websites via ZIP upload with automatic database provisioning, file manager, and backups.

---

## Quick Start (Termux / Linux)

```bash
# 1. Extract the ZIP
cd ~
unzip hosting_platform.zip
cd hosting_platform

# 2. Install Python dependencies
pip install -r requirements.txt --break-system-packages

# 3. Copy and edit environment file (only SECRET_KEY is required)
cp .env.example .env
nano .env   # Change SECRET_KEY at minimum

# 4. Start the app
./start.sh dev
# Open: http://localhost:5000
```

---

## Database Options

### Option A — SQLite (zero config, default)
No setup needed. Works immediately. Each site gets its own SQLite `.db` file stored in `instance/site_dbs/`. Your PHP code connects with:

```php
$db = new PDO('sqlite:/path/to/site_1.db');
```

The exact path is shown on the **Database** page for each site.

### Option B — MariaDB/MySQL (production-grade)
Install MariaDB, then set `MYSQL_ROOT_PASSWORD` in your `.env`. The platform auto-detects this and provisions a real database per site.

**Termux install:**
```bash
pkg install mariadb
mysqld_safe --datadir=$PREFIX/var/lib/mysql &
mysql_secure_installation
# Set root password, then add it to .env
```

**Linux/VPS:**
```bash
sudo apt install mariadb-server
sudo mysql_secure_installation
sudo mysql -e "ALTER USER 'root'@'localhost' IDENTIFIED BY 'yourpassword'; FLUSH PRIVILEGES;"
# Add MYSQL_ROOT_PASSWORD=yourpassword to .env
```

---

## Site URLs

| Environment | URL format |
|---|---|
| `localhost` | `http://localhost:5000/preview/your-site-name` |
| Real domain | `http://your-site-name.yourdomain.com` |

URLs are auto-detected from the request — no config needed.

---

## Production Deployment

```bash
# Install gunicorn + eventlet
pip install gunicorn eventlet --break-system-packages

# Start production server
FLASK_ENV=production ./start.sh prod
```

For Nginx subdomain routing, see `nginx/` folder for config templates.

---

## Admin Panel

Visit `/admin` and log in with the credentials set in `.env`:
- `SUPER_ADMIN_EMAIL`
- `SUPER_ADMIN_PASSWORD`
# hostFiles
