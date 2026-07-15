# Operations

| Field | Value |
|-------|-------|
| Document ID | 0500-CFR-Operations |
| Version | 1.0.0 |
| Last Updated | 2026-07-14 |
| Maintainer | Mark LaPointe <mark@cloudbsd.org> |
| Status | ACTIVE |
| Classification | INTERNAL |

---

## Deployment Matrix

| Platform | Service Manager | Installer | Files |
|----------|-----------------|-----------|-------|
| FreeBSD 14+ | `rc.d` (rc.subr) | port | `contrib/freebsd/`, `deploy/cloudflare-ddns.rc`, `/usr/local/etc/rc.d/cloudflare_ddns` |
| Debian 12+/Ubuntu 22.04+ | systemd | `.deb` | `debian/`, `deploy/cloudflare-ddns.service`, `/lib/systemd/system/cloudflare-ddns.service` |
| Other Linux | systemd (if present), cron, manual | pip | `make package-generic` then `pip install user ...whl` |
| macOS | launchd (planned), manual | pip | `pip install --user ...whl` |

## Standard Install

### FreeBSD via ports (illustrative; submit to ports tree to enable)

```sh
cd /usr/ports/dns/cloudflare-register
make install clean
sysrc cloudflare_ddns_enable=YES
service cloudflare_ddns start
```

### Debian/Ubuntu via .deb

```sh
dpkg -i cloudflare-register_0.2.0-1_all.deb
$EDITOR /etc/cloudflare-register/cloudflare-register.env
systemctl enable --now cloudflare-ddns
```

### Generic (any Linux/macOS)

```sh
python3 -m venv .venv && . .venv/bin/activate
pip install -e .
cloudflare-register init
$EDITOR .env
cloudflare-register service         # foreground; Ctrl-C to stop
```

## Manual / Cron Mode

For hosts without a service supervisor, schedule the sync directly:

```cron
*/5 * * * *  /opt/cloudflare-register/.venv/bin/cloudflare-register sync --once >> /var/log/cloudflare-register.log 2>&1
```

The `sync --once` subcommand runs a single reconciliation cycle, logs to
stderr, and exits non-zero on failures so cron can email the user.

## Service Account

| OS | Account | Created by |
|----|---------|------------|
| FreeBSD | `cloudflare-ddns` | port post-install (planned) |
| Debian/Ubuntu | `cloudflare-ddns` | `debian/postinst` |
| Generic | operator-managed | n/a |

The service account owns `/var/lib/cloudflare-register/`, never runs as
root, and has no `bash` shell.

## Logging

| Sink | Default | How to change |
|------|---------|---------------|
| stderr | yes | Set `LOG_LEVEL=DEBUG` |
| file (`/var/log/cloudflare-register.log`) | via rc.d / systemd redirect | per-system unit / config |

## SIGHUP

Sending `SIGHUP` to the service triggers a settings reload
(`reset_settings_cache(); get_settings()`). Restart for changes that affect
listener ports (`HTTP_HOST`, `HTTP_PORT`).

---

## Change Log

| Version | Date | Author | Change |
|---------|------|--------|--------|
| 1.0.0 | 2026-07-14 | Mark LaPointe | Initial operations document. |

Last Updated: 2026-07-14
Contact: Mark LaPointe <mark@cloudbsd.org>
Classification: INTERNAL
