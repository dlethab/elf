#!/bin/sh
# Opens the FICTIONAL sample archive with the PHP edition (the real archive is not touched). macOS and Linux.
#   ./run-sample.sh             this computer only: http://127.0.0.1:8001
#   ./run-sample.sh --lan       also phones and other devices on the same Wi-Fi
#   ./run-sample.sh --rebuild   start the sample over
# Accounts and password: instance/sample-accounts.txt
cd "$(dirname "$0")" || exit 1
PORT=8001
HOST=127.0.0.1
for a in "$@"; do
  case "$a" in
    --lan) HOST=0.0.0.0 ;;
    --rebuild) REBUILD=1 ;;
    --port=*) PORT="${a#--port=}" ;;
  esac
done
export ELF_ENV=development
if [ -n "$REBUILD" ] || [ ! -f instance/sample.db ]; then
  php bin/elf sample-db || exit 1
fi
grep "password:" instance/sample-accounts.txt
echo "(accounts: instance/sample-accounts.txt)"
export ELF_DATABASE_PATH=instance/sample.db
export ELF_MEDIA_ROOT=instance/sample-media
export ELF_BASE_URL="http://127.0.0.1:$PORT"
if [ "$HOST" = "0.0.0.0" ]; then
  echo "On your phone (same Wi-Fi), open http://<this computer's address>:$PORT"
fi
echo "Open http://127.0.0.1:$PORT (Ctrl+C to stop)"
exec php -S "$HOST:$PORT" -t public public/index.php
