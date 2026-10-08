#!/bin/sh
# Lets one SSH key deploy webos and do nothing else. Run on the server, in the checkout, as
# the user who owns it, with the public key's three parts as arguments:
#
#   sh deploy/authorize-deploy-key.sh ssh-ed25519 AAAA... github-actions-webos
#
# It appends the key to ~/.ssh/authorized_keys with deploy.sh as its forced command and
# `restrict` (no shell, no terminal, no forwarding). So even if the GitHub secret leaks,
# the key can only deploy a commit that is already on origin/master.
set -eu

if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
  echo "Usage: sh deploy/authorize-deploy-key.sh ssh-ed25519 <key> [comment]" >&2
  exit 2
fi
type=$1
key=$2
comment=${3:-webos-deploy}

[ "$type" = ssh-ed25519 ] || { echo "Only ssh-ed25519 keys are accepted." >&2; exit 2; }
case "$key" in
  '' | *[!A-Za-z0-9+/=]*) echo "That doesn't look like a public key." >&2; exit 2 ;;
esac
case "$comment" in
  *[!A-Za-z0-9._@-]*) echo "Keep the comment to letters, digits and . _ @ -" >&2; exit 2 ;;
esac

script="$(cd "$(dirname "$0")" && pwd)/deploy.sh"
case "$script" in
  *[!A-Za-z0-9._/-]*) echo "The checkout's path has characters a forced command can't hold." >&2; exit 2 ;;
esac
line="command=\"sh $script\",restrict $type $key $comment"

dir="$HOME/.ssh"
file="$dir/authorized_keys"
[ -d "$dir" ] || mkdir -m 700 "$dir"
[ -f "$file" ] || (umask 077 && : >"$file")

if grep -qF " $key" "$file"; then
  echo "This key is already in $file. Nothing changed."
  exit 0
fi
# Never glue the new entry onto a last line that has no newline: that would break the key
# on that line.
if [ -s "$file" ] && [ -n "$(tail -c 1 "$file")" ]; then
  printf '\n' >>"$file"
fi
printf '%s\n' "$line" >>"$file"
echo "Added to $file:"
echo "$line"
