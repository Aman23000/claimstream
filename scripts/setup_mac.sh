#!/usr/bin/env bash
# One-shot macOS setup for ClaimStream (Apple Silicon or Intel). Safe to re-run: every step is idempotent.
#   bash scripts/setup_mac.sh            # install + build data/models
#   bash scripts/setup_mac.sh --start    # ...and start the stack at the end
set -euo pipefail
cd "$(dirname "$0")/.."
ok()   { printf "\033[32m✓ %s\033[0m\n" "$*"; }
step() { printf "\n\033[1;34m==> %s\033[0m\n" "$*"; }
die()  { printf "\033[31m✗ %s\033[0m\n" "$*"; exit 1; }

step "1/8 Checking Homebrew"
if ! command -v brew >/dev/null; then
  for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do [[ -x $b ]] && eval "$($b shellenv)"; done
fi
command -v brew >/dev/null || die "Homebrew is not installed. Install it yourself (it needs your password):
  /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"
then re-run this script."
ok "brew $(brew --version | head -1)"

step "2/8 Installing system packages (python 3.12, Java 21, PostgreSQL 16, Redis, libomp)"
for pkg in python@3.12 openjdk@21 postgresql@16 redis libomp; do
  brew list --versions "$pkg" >/dev/null 2>&1 && ok "$pkg already installed" || brew install "$pkg"
done

export JAVA_HOME="$(brew --prefix openjdk@21)/libexec/openjdk.jdk/Contents/Home"
export PATH="$(brew --prefix openjdk@21)/bin:$(brew --prefix postgresql@16)/bin:$(brew --prefix python@3.12)/bin:$PATH"
if ! grep -q "openjdk@21" ~/.zshrc 2>/dev/null; then
  {
    echo ''
    echo '# ClaimStream: Java 21 + PostgreSQL 16 on PATH'
    echo 'export JAVA_HOME="$(brew --prefix openjdk@21)/libexec/openjdk.jdk/Contents/Home"'
    echo 'export PATH="$(brew --prefix openjdk@21)/bin:$(brew --prefix postgresql@16)/bin:$PATH"'
  } >> ~/.zshrc
  ok "added JAVA_HOME/PATH to ~/.zshrc"
fi
java -version 2>&1 | head -1 | grep -q '"21' || die "Java 21 not active (java -version: $(java -version 2>&1 | head -1))"
ok "$(java -version 2>&1 | head -1)"

step "3/8 Starting PostgreSQL and Redis"
brew services start postgresql@16 >/dev/null || true
brew services start redis >/dev/null || true
for i in {1..30}; do pg_isready -h 127.0.0.1 -p 5432 >/dev/null 2>&1 && break; sleep 1; done
pg_isready -h 127.0.0.1 -p 5432 >/dev/null || die "PostgreSQL did not start (try: brew services restart postgresql@16)"
for i in {1..15}; do redis-cli ping >/dev/null 2>&1 && break; sleep 1; done
redis-cli ping | grep -q PONG || die "Redis did not start (try: brew services restart redis)"
psql -h 127.0.0.1 -d postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname='postgres'" | grep -q 1 \
  || createuser -h 127.0.0.1 -s postgres
psql -h 127.0.0.1 -U postgres -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='claimstream'" | grep -q 1 \
  || createdb -h 127.0.0.1 -U postgres claimstream
ok "postgres + redis running, database 'claimstream' ready"

step "4/8 Python virtual environment + libraries (first run takes 5-10 min)"
[[ -d .venv ]] || python3.12 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt
python -c "import lightgbm, torch, pyspark, fastapi, streamlit; print('imports ok')" || die "a Python package failed to import"
ok "venv ready: $(python --version)"

step "5/8 Building + testing the Java rules service"
make rules
ok "rules-service.jar built"

step "6/8 Starting the rules service temporarily (the fraud training uses it as a baseline)"
scripts/run_local.sh stop >/dev/null 2>&1 || true
java -jar rules-service/rules-service.jar > /tmp/claimstream-rules-setup.log 2>&1 &
RULES_PID=$!
trap 'kill $RULES_PID 2>/dev/null || true' EXIT
for i in {1..20}; do curl -fs localhost:8090/health >/dev/null 2>&1 && break; sleep 1; done
curl -fs localhost:8090/health >/dev/null || die "rules service didn't start - see /tmp/claimstream-rules-setup.log"
ok "rules service up on :8090"

step "7/8 Data + models: download -> Postgres -> fraud model -> Spark -> forecast (~3 min)"
export MLFLOW_DISABLE_AGENT_HINT=1
make pipeline
kill $RULES_PID 2>/dev/null || true; trap - EXIT
ok "pipeline complete"

step "8/8 Unit tests"
python -m pytest -q -m "not integration"
ok "setup finished"

if [[ "${1:-}" == "--start" ]]; then
  scripts/run_local.sh start
  sleep 12
  curl -fs localhost:8000/health && echo
  ok "open http://localhost:8501 (dashboard) and http://localhost:8000/docs (API)"
  command -v open >/dev/null && open http://localhost:8501 || true
else
  echo
  echo "Next:  source .venv/bin/activate && make up      -> http://localhost:8501"
fi
