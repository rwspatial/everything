#!/usr/bin/env bash
# The AWS server, on demand (docs/setup/10-production.md). It is STOPPED by default and NOT public: ports 22/80/443
# accept the owner's IP only, and an EventBridge schedule stops it every night at 1 AM America/New_York.
#   up        start it, refresh the owner-IP firewall rule if your IP changed, wait for the site, print the URLs
#   down      stop it (backup=1: upload a database backup to S3 first, ~10 minutes)
#   deploy    up + update the server: src=git (default: pushed master) or src=local (this working tree, uncommitted
#             changes included); data=1 also ships a fresh database backup and the COGs. Then the production checks.
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
