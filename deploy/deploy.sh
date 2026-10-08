#!/bin/sh
# Updates webos on the server to a commit on origin/master, rebuilds it, and waits until
# the panel is healthy again.
#
#   By hand, in the checkout:  sh deploy/deploy.sh            (the latest commit)
#                              sh deploy/deploy.sh <commit>
#   From GitHub Actions:       as the forced command of the deploy key (README, "Deploy on
#                              push"), which sends the commit that passed CI.
#
# It only fast-forwards, and only to a full commit hash already on origin/master, so
# nothing sent over SSH can move the server backwards, onto another branch, or run anything
# else. It never reinstalls the host agent: that needs root, so it stays a manual step.
set -eu

cd "$(dirname "$0")/.."

# One deploy at a time.
exec 9>.git/webos-deploy.lock
if ! flock -n 9; then
  echo "Another deploy is running, so this one stops here." >&2
  exit 1
fi

if [ "$(git symbolic-ref --quiet --short HEAD || true)" != master ]; then
  echo "The checkout isn't on master; refusing to deploy." >&2
  exit 2
fi

git fetch --quiet origin master
commit="${SSH_ORIGINAL_COMMAND:-${1:-}}"
[ -n "$commit" ] || commit=$(git rev-parse origin/master)
case "$commit" in
  *[!0-9a-f]*)
    echo "Refused: not a commit hash." >&2
    exit 2
    ;;
esac
if [ "${#commit}" -ne 40 ] || ! git merge-base --is-ancestor "$commit" origin/master 2>/dev/null; then
  echo "Refused: not a full commit hash on origin/master." >&2
  exit 2
fi

before=$(git rev-parse HEAD)
git merge --ff-only --quiet "$commit"
after=$(git rev-parse HEAD)
if [ "$before" = "$after" ]; then
  echo "Already at $(git log -1 --format='%h %s')."
else
  git log --format='%h %s' "$before..$after"
fi

docker compose up -d --build

# The image's health check calls /healthz every 30 s, so a fresh container reports
# "starting" for up to half a minute.
container=$(docker compose ps -q webos)
tries=0
while :; do
  status=$(docker inspect --format '{{.State.Health.Status}}' "$container" 2>/dev/null || echo missing)
  [ "$status" = healthy ] && break
  tries=$((tries + 1))
  if [ "$status" = unhealthy ] || [ "$tries" -ge 60 ]; then
    echo "webos isn't healthy ($status). See: docker compose logs --tail=100 webos" >&2
    exit 1
  fi
  sleep 2
done
echo "webos is up at $(git log -1 --format='%h %s')."

if ! git diff --quiet "$before" "$after" -- agent/; then
  # Shows as a warning on the GitHub Actions run, and reads fine in a terminal.
  echo "::warning title=Host agent changed::agent/ changed. On the server, run: sudo sh agent/install.sh"
fi
