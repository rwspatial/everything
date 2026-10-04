# 10 · Production mode and the first public server

Production mode runs the **same code and images** as development, with a different Compose overlay and proxy
config. Nothing is forked: what differs lives in `compose.prod.yaml`, `services/proxy/Caddyfile.prod` and the
server's `.env`.

```
Internet ──80/443──▶ proxy: public site ({$SITE_ADDRESS}, automatic HTTPS)
                       │  stamps X-Public-Site: 1 → core-api shows only maps with status "ready"
                       │  /admin, /api/admin, /projects/*.json → 404     config.json → publicMode: true
You ──ssh -L 8081──▶ proxy: admin listener (server's 127.0.0.1:8081 only)
                       │  full site + /admin behind the existing login; drafts visible
```

## What the public sees

| | Public site | Admin listener |
|---|---|---|
| Maps on the hub and home page | status `ready` only | all |
| A draft's map, charts, reports (`/p/<slug>`, `/api/projects/<slug>/…`) | 404 | yes |
| `/admin`, `/api/admin/*` | 404, even with the login | login required |
| Raw manifests `/projects/*.json` | 404 | 404 (production reads the database) |
| Admin link, "Add a project", `/new` | hidden / 404 | shown |
| Data API `/tiles/*`, rasters `/raster/*` | public (tiles cached 1 h, rasters 1 day) | same |
| Database port | not published | not published |

The filter is enforced in core-api, not only in the page: a guessed URL for a draft is a 404.

## Publishing a map

Set `"status": "ready"` in `projects/<slug>/project.json` and run `./mapgen sync` (or `./mapgen apply <slug>`).
Back to `"draft"` hides it again. A `ready` project may not contain to-do layers (`E_READY_TODO`).
Launch set (2026-10-03): maine-overview, maine-water, maine-terrain, maine-places, maine-transportation,
maine-facilities.

## Try it locally

```bash
make prod-local     # production proxy: public site http://localhost:8090, admin http://localhost:8081
make verify-prod    # 19 checks: no admin or drafts in public, admin works on 8081
make dev-proxy      # back to the dev proxy on http://localhost:8080
```

Only the proxy changes here; the rest of the stack keeps its dev settings (e.g. tiles are not cached).

## First server (one VM, plan: spatial-app-architecture §5)

1. A Linux VM with Docker (e.g. EC2, 4 vCPU / 16 GB, 200 GB disk for the database and COGs), ports 80 and 443
   open to the internet, 22 open to your address only. Point the domain's DNS A record at it.
2. Clone the repository at the `prod` branch (below). Copy the dev `.env`, then change:
   ```
   COMPOSE_FILE=compose.yaml:compose.prod.yaml
   SITE_ADDRESS=maps.example.org        # your domain: Caddy gets the certificate itself
   ACME_EMAIL=you@example.org           # Let's Encrypt expiry notices
   ```
   and generate fresh passwords (`make env` on a new checkout writes random ones).
3. Bring the data over: `make backup` here, copy the dump and `data/cog/` to the server, `make restore` there
   (docs/setup/03-reinstall-reset.md). Re-importing everything from the recipes also works but takes hours.
4. `make up`, then `make verify-prod PUBLIC_URL=https://maps.example.org`.
5. Admin from your machine: `ssh -L 8081:127.0.0.1:8081 <server>`, then open http://localhost:8081/admin.

## COGs on S3 and off-site backups

Two Compose overlays, added after the dev or prod one:

| Overlay | Does |
|---|---|
| `compose.s3.yaml` | titiler reads COGs from `s3://$COG_S3_BUCKET/$COG_S3_PREFIX` (`COG_ROOT`, also used by core-api and the health checks); adds `make cog-sync` and `make backup-offsite` |
| `compose.s3local.yaml` | local test only: a SeaweedFS S3 gateway stands in for AWS (MinIO no longer ships free images) |

```bash
# server .env (AWS): COMPOSE_FILE=compose.yaml:compose.prod.yaml:compose.s3.yaml, COG_S3_BUCKET=…, BACKUP_S3_BUCKET=…
make cog-sync          # mirror data/cog -> the bucket (after every raster import); 3.4 GB took ~2 min locally
make backup-offsite    # make backup + upload the dump; the bucket expires backups after BACKUP_KEEP_DAYS (30)
```

- Imports still write COGs to `data/cog`; the bucket is the serving copy. Without `compose.s3.yaml` nothing changes.
- On EC2, leave `COG_S3_ACCESS_KEY`/`COG_S3_SECRET_KEY` empty and give the instance a role that can read the COG
  bucket and write both buckets. Keep the backup bucket private.
- Nightly backup on the server (`crontab -e`), with `BACKUP_PRUNE_LOCAL=1` in `.env` so local dumps older than
  7 days are removed after a successful upload:
  ```
  15 3 * * * cd /srv/everything && make backup-offsite >> data/backups/backup.log 2>&1
  ```
- A full dump is about 3.4 GB and takes ~8 minutes (2026-10-03). Test a restore from the bucket before launch.
- To try locally: `COMPOSE_FILE=compose.yaml:compose.dev.yaml:compose.s3.yaml:compose.s3local.yaml`, then
  `docker compose up -d s3local`, recreate `titiler proxy core-api`, `make cog-sync`.

## The AWS server (on demand, private)

### How on-demand hosting works

There is **one server, and it is off unless you turn it on.** It has no fixed address and no domain yet: each time it
starts, AWS gives it a new public IP, and the start command prints it. Only your home connection can open it.

| State | What it means | Get there with | Address | Who can see it | Cost |
|---|---|---|---|---|---|
| **Stopped** (default) | Server off; data kept on its disk | `make aws-down`, or automatically at 1 AM Eastern | none | nobody | ≈ $3.20/month (disk) |
| **Running, private** | The site is up in production mode: published maps only, no admin pages | `make aws-up` (≈ 1 min) | `http://<IP>/`, printed by the command; `make aws-status` shows it again | your home IP (74.75.120.122) only | ≈ $0.10/hour |
| **Running + admin** | Same, plus the admin pages through an SSH tunnel | `make aws-tunnel` in a second terminal | `http://localhost:8081/admin` | you (SSH key + admin login) | same |
| **Updated** | The server runs your latest code (and optionally data) | `make aws-deploy src=local` (≈ 40 s) or `src=git`; `data=1` adds database + COGs (≈ 15 min) | printed at the end | your home IP only | same |
| **Public** (not yet) | Anyone can open it, on a domain with HTTPS | needs a domain (see "Domain" below) and opening ports 80/443 to everyone | the domain | everyone | same + domain (≈ $15/year) |

A normal session: `make aws-deploy src=local` → open the printed address → (`make aws-tunnel` for admin) →
`make aws-down`.

- **The address changes at every start** (no Elastic IP: one costs ≈ $3.65/month even while stopped). A domain will
  give one stable name; `make aws-up` will point it at the new IP each time.
- **If your home IP changes,** `make aws-up` moves the firewall rule to the new IP. A phone on mobile data, or anyone
  else, gets no response.
- **What runs there:** the published site, tiles, rasters from S3 and charts. Not there: imports, the R/Python analysis
  workers and the PDF reporter (they stay on the workstation), so PDFs are made locally.
- **Credit:** costs come out of the AWS Free-plan credit ($100, until 2027-04-03).

### Domain (when the site goes public)

The Free plan does not allow registering domains in Route 53. Options, decided later:

1. **Upgrade to the Paid plan** (unused credit stays valid; the domain itself, ≈ $15/year, is billed to the card because
   credits cannot pay for domains). Add an AWS Budgets alert (e.g. $10 and $25/month). Then Route 53 + automatic DNS
   update in `make aws-up` + HTTPS through Route 53 (DNS-01), even while the firewall stays private.
2. **Buy the domain elsewhere** (e.g. Cloudflare Registrar, at cost, with free DNS): works on the Free plan; `make aws-up`
   updates the record through Cloudflare's API and HTTPS uses Cloudflare DNS.
3. **No domain** while testing privately: the printed IP is enough.


Created 2026-10-03 in account 277659481909, **us-east-2**. It is **stopped by default and not public**: ports
22/80/443 accept the owner's IP only, and a schedule stops it every night at 1 AM America/New_York.

```bash
make aws-deploy    # start + update to the pushed master, migrate, re-apply views, sync projects, run the checks
make aws-deploy src=local   # same with this working tree (uncommitted UI work included); ~40 s when only code changed
make aws-deploy data=1      # also a fresh database backup + COGs (restored on the server; ~15 min)
make aws-up        # start (moves the owner-only firewall rule if your IP changed), wait, print the URL
make aws-tunnel    # admin listener -> http://localhost:8081/admin
make aws-ssh       # a shell (the stack lives in /srv/everything; .env there is the server's)
make aws-down      # stop; `make aws-down backup=1` uploads a database backup to S3 first (~10 min)
make aws-status
```

| Resource | Name / id | Notes |
|---|---|---|
| EC2 instance | `everything-server` (i-0b9f8014ab2d88409) | m7i-flex.large (2 vCPU, 8 GB), Ubuntu 24.04, 40 GB gp3 encrypted, no Elastic IP: the address changes at each start |
| Security group | `everything-server` (sg-0000cb75cd8082959) | 22, 80, 443 from the owner's IP (/32, description `owner`) only |
| Key pair | `everything-server` | private key: `~/.ssh/everything-server.pem` on the workstation only |
| S3 buckets | `everything-cog-277659481909`, `everything-backups-277659481909` | public access blocked; COGs under `cog/`, dumps under `backups/` (expire after 30 days) |
| IAM | role + instance profile `everything-server` (those two buckets only); role `everything-autostop` | the server needs no stored keys |
| Schedule | EventBridge Scheduler `everything-autostop` | `cron(0 1 * * ? *)` America/New_York -> ec2:StopInstances |

Everything carries the tag `project=everything`.

**Costs** (us-east-2 prices, 2026-10-03): stopped ≈ $3.20/month for the disk plus a few cents of S3; running
≈ $0.10/hour (instance $0.096 + public IPv4 $0.005). The account is on the AWS **Free plan**: $100 of credits
until **2027-04-03**; upgrade to the Paid plan in the Billing console before then (or before the credits run
out), or AWS closes the account. The Free plan only allows free-tier instance types (m7i-flex.large is the
largest).

**Deploys:** `src=git` resets the server to `origin/master` (and removes anything a `src=local` deploy copied);
`src=local` copies the files git tracks plus new ones it does not ignore. Projects are registered with `mapgen`
running in the core-api container (no geotools image on the server); the dashboard's "used by" column is not
refreshed there. Generated PDFs stay on the machine that printed them (the reporter does not run on the server).

**What runs there:** the core stack only (database, tiPG, titiler from S3, core-api, site, proxy) in production
mode. Imports, the R/Python workers and the reporter stay on the workstation; data goes over as a database
backup (`make backup-offsite` here, then `make restore` there) and `make cog-sync`.

**Removing it all:** terminate the instance (deletes its disk), then delete the schedule, the two roles, the
instance profile, the security group, the key pair and the two buckets (`project=everything` tag).

## Releases: the `prod` branch

`prod` is a pointer to what is deployed, not a second codebase: it only ever fast-forwards from `master`.

```bash
git checkout prod && git merge --ff-only master && git push    # release
# on the server
git pull --ff-only && make up && make migrate && ./mapgen sync && make verify-prod
```

Never commit to `prod` directly; fix on `master` and release again.

## Before going public (checklist)

- [ ] `make verify-prod` passes against the real domain.
- [ ] Attribution: every published map credits its sources as their licences require (Overture, OpenFreeMap,
      HIFLD, MEGIS …); the report pages list them under Sources.
- [ ] Backups: the nightly `make backup-offsite` cron is installed, and one restore from the bucket was tested.
- [x] Analysis outputs (`pub.analysis_sandbox__job_*`) are 404 on the public site (still listed by name in
      `/tiles/collections`).
- [ ] COGs: `make cog-sync` done and `compose.s3.yaml` in COMPOSE_FILE (`make verify-prod` passes with it).
- [ ] Next steps (plan §5.2): CloudFront in front for tile caching, then RDS and ECS when traffic or reliability
      calls for it.
