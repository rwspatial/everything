#!/usr/bin/env bash
# The AWS server, on demand (docs/setup/10-production.md). It is STOPPED by default and NOT public: ports 22/80/443
# accept the owner's IP only, and an EventBridge schedule stops it every night at 1 AM America/New_York.
#   up        start it, refresh the owner-IP firewall rule if your IP changed, wait for the site, print the URLs
#   down      stop it (backup=1: upload a database backup to S3 first, ~10 minutes)
#   deploy    up + update the server: src=git (default: pushed master) or src=local (this working tree, uncommitted
#             changes included); data=1 also ships a fresh database backup and the COGs. Then the production checks.
#   present   up + present mode (scripts/present.sh): the public site at a temporary https://….trycloudflare.com link,
#             read-only, admin off; checked from outside before the link is printed. minutes=90 (then it powers off),
#             password=1 (a viewer password), src=local|git (deploy first). make aws-down ends it.
#   status    state, address, running since
#   ssh       a shell on the server;  tunnel: the admin listener on http://localhost:8081
set -euo pipefail
export AWS_REGION="${AWS_REGION:-us-east-2}"
NAME="${AWS_SERVER_NAME:-everything-server}"
KEY="${AWS_SSH_KEY:-$HOME/.ssh/everything-server.pem}"
SSH=(ssh -i "$KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15)
REPO="$(cd "$(dirname "$0")/.." && pwd)"
COG_BUCKET="${COG_S3_BUCKET:-everything-cog-277659481909}"
BACKUP_BUCKET="${BACKUP_S3_BUCKET:-everything-backups-277659481909}"

instance() {
  aws ec2 describe-instances --filters "Name=tag:Name,Values=$NAME" \
    "Name=instance-state-name,Values=pending,running,stopping,stopped" \
    --query 'Reservations[0].Instances[0].[InstanceId,State.Name,PublicIpAddress,LaunchTime,SecurityGroups[0].GroupId]' --output text
}
read_instance() { read -r IID STATE IP SINCE SG < <(instance); [[ $IID != None ]] || { echo "no instance named $NAME" >&2; exit 1; }; }

allow_my_ip() {  # keep the owner-only rules on the current public IP (never 0.0.0.0/0)
  local me old
  me="$(curl -s --max-time 10 https://checkip.amazonaws.com)/32"
  local allowed
  allowed=$(aws ec2 describe-security-groups --group-ids "$SG" \
        --query "SecurityGroups[0].IpPermissions[?FromPort==\`22\`].IpRanges[].CidrIp" --output text)
  grep -qw -- "${me%/32}/32" <<<"$allowed" && return 0
  old=$(aws ec2 describe-security-groups --group-ids "$SG" \
        --query "SecurityGroups[0].IpPermissions[?FromPort==\`22\`].IpRanges[?Description=='owner'].CidrIp[]" --output text | awk '{print $1}')
  old=${old:-None}
  echo "your IP changed ($old -> $me): moving the owner-only rules"
  for port in 22 80 443; do
    [[ $old != None ]] && aws ec2 revoke-security-group-ingress --group-id "$SG" --protocol tcp --port $port --cidr "$old" >/dev/null || true
    aws ec2 authorize-security-group-ingress --group-id "$SG" \
      --ip-permissions "IpProtocol=tcp,FromPort=$port,ToPort=$port,IpRanges=[{CidrIp=$me,Description=owner}]" >/dev/null
  done
}

# From outside, through the public link: nothing can be changed, admin does not exist, only published maps.
present_checks() {
  local url=$1; shift
  local auth=("$@") fail=0 c body
  pass() { echo "  PASS $1"; }
  bad() { echo "  FAIL $1"; fail=1; }
  c=$(curl -s -o /dev/null -w '%{http_code}' "${auth[@]}" "$url/maps"); [[ $c == 200 ]] && pass "the site loads ($url/maps)" || bad "the site: HTTP $c"
  if ((${#auth[@]})); then
    c=$(curl -s -o /dev/null -w '%{http_code}' "$url/maps"); [[ $c == 401 ]] && pass "without the viewer password: refused" || bad "no password asked: HTTP $c"
  fi
  for m in POST PUT DELETE; do
    c=$(curl -s -o /dev/null -w '%{http_code}' "${auth[@]}" -X $m -H 'Content-Type: application/json' -d '{}' "$url/api/projects/maine-overview")
    [[ $c == 405 || $c == 404 ]] && pass "$m /api/projects refused ($c)" || bad "$m /api/projects: HTTP $c"
  done
  # Admin paths must not exist: asked with the admin login (or, behind a viewer password, as the viewer).
  local who=(-u "${ADMIN_USER:-admin}:${ADMIN_PASSWORD:-x}")
  ((${#auth[@]})) && who=("${auth[@]}")
  for p in /admin /admin/projects /api/admin/datasets /api/admin/auth /projects/index.json; do
    c=$(curl -s -o /dev/null -w '%{http_code}' "${who[@]}" "$url$p")
    [[ $c == 404 ]] && pass "$p not served ($c)" || bad "$p: HTTP $c"
  done
  body=$(curl -s "${auth[@]}" -H 'X-Public-Site: 0' "$url/api/projects")
  python3 -c 'import json,sys; d=json.loads(sys.argv[1])["projects"]; s={p["status"] for p in d}; sys.exit(0 if d and s=={"ready"} else 1)' "$body" \
    && pass "only published maps listed (even with a forged X-Public-Site header)" || bad "unpublished maps are listed"
  c=$(curl -s -o /dev/null -w '%{http_code}' "${auth[@]}" "$url/tiles/collections")
  [[ $c == 404 ]] && pass "the Data API catalogue is not public ($c)" || bad "Data API catalogue: HTTP $c"
  c=$(curl -s -o /dev/null -w '%{http_code}' "${auth[@]}" "$url/tiles/collections/pub.maine_coast__growing_areas/tiles/WebMercatorQuad/7/38/46")
  [[ $c == 404 ]] && pass "draft data not served ($c)" || bad "draft tiles served: HTTP $c"
  c=$(curl -s -o /dev/null -w '%{http_code}' "${auth[@]}" "$url/tiles/collections/pub.maine_water__stream_gauges/tiles/WebMercatorQuad/7/38/46")
  [[ $c == 200 || $c == 204 ]] && pass "published map tiles still served ($c)" || bad "published tiles: HTTP $c"
  body=$(curl -s "${auth[@]}" "$url/raster/maine/dem_30m/info?url=s3://$BACKUP_BUCKET/backups/x.dump")
  grep -q '"bounds"' <<<"$body" && pass "raster tiles ignore a swapped file path" || bad "raster info: ${body:0:120}"
  open=$(aws ec2 describe-security-groups --group-ids "$SG" --query "SecurityGroups[0].IpPermissions[].IpRanges[?CidrIp=='0.0.0.0/0'].CidrIp" --output text)
  [[ -z $open ]] && pass "firewall: no port open to the internet" || bad "firewall has 0.0.0.0/0 rules"
  return $fail
}

wait_site() {
  for _ in $(seq 1 60); do curl -s -o /dev/null --max-time 5 "http://$IP/healthz" && return 0; sleep 5; done
  echo "the site did not answer on http://$IP/" >&2; return 1
}

case "${1:-status}" in
  deploy)
    "$0" up >/dev/null
    read_instance
    R="ubuntu@$IP"
    if [[ ${SRC:-git} == local ]]; then
      echo "code: this working tree (tracked + new files, nothing git ignores)"
      git -C "$REPO" ls-files -co --exclude-standard -z | tar -C "$REPO" --null -T - -czf - \
        | "${SSH[@]}" "$R" 'cd /srv/everything && tar -xzf -'
    else
      echo "code: origin/master"
      "${SSH[@]}" "$R" 'cd /srv/everything && git fetch -q origin && git reset -q --hard origin/master && git clean -fdq && git log --oneline -1'
    fi
    if [[ ${DATA:-0} == 1 ]]; then
      echo "data: fresh backup + COGs (takes a while)"
      (cd "$REPO" && bash scripts/ops.sh backup)
      dump=$(ls -1t "$REPO"/data/backups/*.dump | head -1); name=$(basename "$dump")
      aws s3 cp "$dump" "s3://$BACKUP_BUCKET/backups/$name" --no-progress
      aws s3 sync "$REPO/data/cog" "s3://$COG_BUCKET/cog" --delete --no-progress \
        --exclude ".versions/*" --exclude "*.tmp.tif" --exclude ".*" --exclude "*/.*"
      "${SSH[@]}" "$R" "cd /srv/everything && docker run --rm -u \$(id -u):\$(id -g) -e HOME=/tmp -e AWS_DEFAULT_REGION=$AWS_REGION \
        -v \$PWD/data/backups:/b amazon/aws-cli:2.27.50 s3 cp s3://$BACKUP_BUCKET/backups/$name /b/$name --no-progress \
        && CONFIRM=yes make restore b=data/backups/$name && find data/backups -name '*.dump' ! -name '$name' -delete"
    fi
    echo "server: build what changed, migrate, views, projects"
    "${SSH[@]}" "$R" 'set -e; cd /srv/everything
      [ -f scripts/present.sh ] && bash scripts/present.sh off >/dev/null
      docker compose up -d --build --remove-orphans 2>&1 | grep -E "Built|Recreated|Error" || true
      docker compose run --rm migrator migrate 2>&1 | grep -E "Applying|Error" || true
      docker compose run --rm migrator seed 2>&1 | grep -iE "error" || true
      docker compose restart tipg >/dev/null
      docker compose run --rm --no-deps -T -v "$PWD/scripts:/w/scripts:ro" -v "$PWD/contracts:/w/contracts:ro" \
        -v "$PWD/projects:/w/projects:ro" --entrypoint sh core-api \
        -c "MAPGEN_APP_DSN=\$PROJECTS_DATABASE_URL TRIGGERED_BY=deploy python /w/scripts/mapgen.py sync" 2>&1 | grep -vE "unchanged|^ ?Container" || true
      bash scripts/ops.sh wait >/dev/null'
    wait_site
    echo "checks (admin through a temporary tunnel on localhost:18081)"
    "${SSH[@]}" -N -o ExitOnForwardFailure=yes -L 18081:127.0.0.1:8081 "$R" & tunnel=$!
    sleep 3
    rc=0
    out=$(cd "$REPO" && set -a && . ./.env && set +a && COMPOSE_FILE= PUBLIC_URL="http://$IP" ADMIN_URL=http://localhost:18081 \
      bash scripts/verify_prod.sh) || rc=$?
    grep -E "FAIL|PASSED" <<<"$out"
    kill "$tunnel" 2>/dev/null || true
    echo
    echo "  deployed: http://$IP/   (your IP only; make aws-down when done)"
    exit $rc
    ;;
  up)
    read_instance
    allow_my_ip
    if [[ $STATE != running ]]; then
      echo "starting $IID ..."
      aws ec2 start-instances --instance-ids "$IID" >/dev/null
      aws ec2 wait instance-running --instance-ids "$IID"
      read_instance
    fi
    echo "waiting for the site on http://$IP/ ..."
    wait_site || true
    # A present session left on (or interrupted) is switched off: admin back, database writable, no tunnel.
    [[ ${KEEP_PRESENT:-0} == 1 ]] || "${SSH[@]}" "ubuntu@$IP" 'cd /srv/everything && [ -f scripts/present.sh ] && bash scripts/present.sh off >/dev/null' || true
    curl -s -o /dev/null -w "site: HTTP %{http_code}\n" --max-time 10 "http://$IP/" || true
    echo
    echo "  site (your IP only):  http://$IP/"
    echo "  admin:                make aws-tunnel   then http://localhost:8081/admin"
    echo "  stop when done:       make aws-down     (it also stops itself at 1 AM)"
    ;;
  down)
    read_instance
    if [[ $STATE == running && ${BACKUP:-0} == 1 ]]; then
      echo "uploading a database backup first ..."
      "${SSH[@]}" "ubuntu@$IP" 'cd /srv/everything && make backup-offsite'
    fi
    if [[ $STATE != stopped ]]; then
      aws ec2 stop-instances --instance-ids "$IID" >/dev/null
      echo "stopping $IID ..."
      aws ec2 wait instance-stopped --instance-ids "$IID"
    fi
    echo "stopped: only its disk is billed now"
    ;;
  present)
    if [[ -n ${SRC:-} ]]; then DATA=0 "$0" deploy | tail -3; else "$0" up >/dev/null; fi
    read_instance
    R="ubuntu@$IP"
    # The present-mode files go up with each session, so it works on whatever code the server has.
    tar -C "$REPO" -czf - scripts/present.sh compose.present.yaml services/proxy/Caddyfile.prod \
      | "${SSH[@]}" "$R" 'cd /srv/everything && tar -xzf -'
    pw=""; auth=()
    if [[ ${PASSWORD:-0} == 1 ]]; then
      pw=$(python3 -c 'import secrets; print("".join(secrets.choice("abcdefghijkmnpqrstuvwxyz23456789") for _ in range(12)))')
      auth=(-u "viewer:$pw")
    fi
    echo "present mode: read-only, admin off, tunnel starting ..."
    url=$("${SSH[@]}" "$R" "cd /srv/everything && bash scripts/present.sh on ${MINUTES:-90} '$pw'" | sed -n 's/^URL=//p')
    [[ -n $url ]] || { echo "present mode did not start; switching it off" >&2; "${SSH[@]}" "$R" 'cd /srv/everything && bash scripts/present.sh off' >/dev/null; exit 1; }
    echo "checks (on the server, then from outside through $url):"
    rc=0
    "${SSH[@]}" "$R" 'cd /srv/everything && bash scripts/present.sh check' | sed 's/^/  /' || rc=1
    for _ in $(seq 1 20); do curl -s -o /dev/null --max-time 5 "${auth[@]}" "$url/healthz" && break; sleep 3; done
    (set -a; [[ -f $REPO/.env ]] && . "$REPO/.env"; set +a; present_checks "$url" "${auth[@]}") || rc=1
    if [[ $rc != 0 ]]; then
      echo "a check failed: the link is closed again (present mode off)." >&2
      echo "if 'admin login refused' failed, the server runs older code: make aws-present src=local" >&2
      "${SSH[@]}" "$R" 'cd /srv/everything && bash scripts/present.sh off' >/dev/null
      exit 1
    fi
    echo
    echo "  ┌ PRESENTING ─────────────────────────────────────────────────────────────"
    echo "  │ link:      $url"
    [[ -n $pw ]] && echo "  │ password:  user viewer, password $pw"
    echo "  │ read-only: admin is off, nothing can be changed; only published maps"
    echo "  │ ends:      make aws-down   (or by itself in ${MINUTES:-90} minutes, and at 1 AM)"
    echo "  └─────────────────────────────────────────────────────────────────────────"
    ;;
  status)
    read_instance
    [[ $IP == None ]] && IP=""
    echo "$NAME ($IID): $STATE${IP:+, http://$IP/}$([[ $STATE == running ]] && echo ", running since $SINCE")"
    ;;
  ssh)
    read_instance; [[ $STATE == running ]] || { echo "not running (make aws-up)"; exit 1; }
    exec "${SSH[@]}" "ubuntu@$IP"
    ;;
  tunnel)
    read_instance; [[ $STATE == running ]] || { echo "not running (make aws-up)"; exit 1; }
    echo "admin on http://localhost:8081/admin (Ctrl-C to close)"
    exec "${SSH[@]}" -N -L 8081:127.0.0.1:8081 "ubuntu@$IP"
    ;;
  *) sed -n '2,8p' "$0"; exit 2 ;;
esac
