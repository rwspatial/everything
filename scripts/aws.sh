#!/usr/bin/env bash
# The AWS server, on demand (docs/setup/10-production.md). It is STOPPED by default and NOT public: ports 22/80/443
# accept the owner's IP only, and an EventBridge schedule stops it every night at 1 AM America/New_York.
#   up        start it, refresh the owner-IP firewall rule if your IP changed, wait for the site, print the URLs
#   down      stop it (backup=1: upload a database backup to S3 first, ~10 minutes)
#   status    state, address, running since
#   ssh       a shell on the server;  tunnel: the admin listener on http://localhost:8081
set -euo pipefail
export AWS_REGION="${AWS_REGION:-us-east-2}"
NAME="${AWS_SERVER_NAME:-everything-server}"
KEY="${AWS_SSH_KEY:-$HOME/.ssh/everything-server.pem}"
SSH=(ssh -i "$KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15)

instance() {
  aws ec2 describe-instances --filters "Name=tag:Name,Values=$NAME" \
    "Name=instance-state-name,Values=pending,running,stopping,stopped" \
    --query 'Reservations[0].Instances[0].[InstanceId,State.Name,PublicIpAddress,LaunchTime,SecurityGroups[0].GroupId]' --output text
}
read_instance() { read -r IID STATE IP SINCE SG < <(instance); [[ $IID != None ]] || { echo "no instance named $NAME" >&2; exit 1; }; }

allow_my_ip() {  # keep the owner-only rules on the current public IP (never 0.0.0.0/0)
  local me old
  me="$(curl -s --max-time 10 https://checkip.amazonaws.com)/32"
  old=$(aws ec2 describe-security-groups --group-ids "$SG" \
        --query "SecurityGroups[0].IpPermissions[?FromPort==\`22\`].IpRanges[?Description=='owner'].CidrIp | [0][0]" --output text)
  [[ $old == "$me" ]] && return 0
  echo "your IP changed ($old -> $me): moving the owner-only rules"
  for port in 22 80 443; do
    [[ $old != None ]] && aws ec2 revoke-security-group-ingress --group-id "$SG" --protocol tcp --port $port --cidr "$old" >/dev/null || true
    aws ec2 authorize-security-group-ingress --group-id "$SG" \
      --ip-permissions "IpProtocol=tcp,FromPort=$port,ToPort=$port,IpRanges=[{CidrIp=$me,Description=owner}]" >/dev/null
  done
}

case "${1:-status}" in
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
    for _ in $(seq 1 60); do curl -s -o /dev/null --max-time 5 "http://$IP/healthz" && break; sleep 5; done
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
