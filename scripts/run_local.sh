#!/usr/bin/env bash
# Start / stop the local demo stack without Docker (Postgres + Redis must already be running).
#   scripts/run_local.sh start   |   scripts/run_local.sh stop
set -euo pipefail
cd "$(dirname "$0")/.."
RUN=.run; mkdir -p "$RUN"

start() {
  local name=$1; shift
  if [[ -f $RUN/$name.pid ]] && kill -0 "$(cat $RUN/$name.pid)" 2>/dev/null; then echo "$name already running"; return; fi
  nohup "$@" > "$RUN/$name.log" 2>&1 &
  echo $! > "$RUN/$name.pid"; echo "started $name (pid $!)"
}

case "${1:-start}" in
  start)
    start rules     java -jar rules-service/rules-service.jar
    sleep 2
    start processor python3 -m claimstream.stream.processor --workers "${WORKERS:-4}"
    start api       uvicorn claimstream.api.main:app --host 0.0.0.0 --port 8000
    start producer  python3 -m claimstream.stream.producer --rate "${RATE:-8}"
    start dashboard streamlit run dashboard/app.py --server.port 8501
    echo "dashboard: http://localhost:8501   api docs: http://localhost:8000/docs" ;;
  stop)
    for f in "$RUN"/*.pid; do [[ -f $f ]] && kill "$(cat "$f")" 2>/dev/null && echo "stopped $(basename "$f" .pid)"; rm -f "$f"; done ;;
  *) echo "usage: $0 start|stop"; exit 1 ;;
esac
