#!/usr/bin/env bash
# =============================================================================
# File: e2e_stack.sh
# Version: 3
# Path: ay_platform_core/scripts/e2e_stack.sh
# Description: One-stop helper for the system-test stack.
#              Wraps `docker compose` + seed + `pytest tests/system/`.
#
#              v3: pass `--env-file <ENV_FILE>` to every `docker compose`
#              invocation so Compose's ${VAR} substitution reads from
#              the test env file (R-100-118 v2). Without this, the root
#              credentials referenced by the `arangodb` and `minio`
#              services would not resolve.
#              v2: moved from /workspace/scripts/ to
#              ay_platform_core/scripts/. Compose file lives alongside the
#              tests at ay_platform_core/tests/docker-compose.yml.
#
# Usage (from anywhere — this script resolves its own location):
#   ./ay_platform_core/scripts/e2e_stack.sh up        # build + start
#   ./ay_platform_core/scripts/e2e_stack.sh down      # tear down + volumes
#   ./ay_platform_core/scripts/e2e_stack.sh seed      # inject test data
#   ./ay_platform_core/scripts/e2e_stack.sh system    # pytest tests/system/
#   ./ay_platform_core/scripts/e2e_stack.sh full      # up + seed + system
#   ./ay_platform_core/scripts/e2e_stack.sh status    # compose ps
#   ./ay_platform_core/scripts/e2e_stack.sh logs <svc> # tail service logs
# =============================================================================

set -euo pipefail

# Resolve absolute paths from the script's own location so the helper works
# regardless of the caller's cwd.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AY_CORE="$(cd "$SCRIPT_DIR/.." && pwd)"                   # .../ay_platform_core
MONOREPO_ROOT="$(cd "$AY_CORE/.." && pwd)"                # .../<monorepo>
COMPOSE_FILE="$AY_CORE/tests/docker-compose.yml"
ENV_FILE="$AY_CORE/tests/.env.test"

STACK_BASE_URL="${STACK_BASE_URL:-http://localhost}"

_require_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "ERROR: docker CLI not found on PATH" >&2
    exit 1
  fi
}

cmd_up() {
  _require_docker
  echo "==> Building images + starting stack"
  echo "    compose file: $COMPOSE_FILE"
  echo "    build ctx:    $MONOREPO_ROOT"
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d --build
  echo "==> Stack is starting; services will report healthy shortly"
  echo "    Traefik dashboard: http://localhost:8080"
  echo "    Public API:        $STACK_BASE_URL"
}

cmd_down() {
  _require_docker
  echo "==> Tearing down stack + volumes"
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" down -v --remove-orphans
}

cmd_status() {
  _require_docker
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps
}

cmd_logs() {
  _require_docker
  local service="${1:-}"
  if [[ -z "$service" ]]; then
    echo "usage: $0 logs <service-name>" >&2
    exit 2
  fi
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" logs -f "$service"
}

cmd_seed() {
  echo "==> Seeding test data via $STACK_BASE_URL"
  (cd "$AY_CORE" && \
    STACK_BASE_URL="$STACK_BASE_URL" \
    python -m ay_platform_core.scripts.seed_e2e --base-url "$STACK_BASE_URL")
}

cmd_system() {
  echo "==> Running system tests against $STACK_BASE_URL"
  (cd "$AY_CORE" && \
    STACK_BASE_URL="$STACK_BASE_URL" \
    python -m pytest tests/system -v --no-cov)
}

cmd_full() {
  cmd_up
  echo "==> Waiting 5 s for images to settle..."
  sleep 5
  cmd_seed
  cmd_system
}

main() {
  local sub="${1:-}"
  case "$sub" in
    up)     cmd_up ;;
    down)   cmd_down ;;
    status) cmd_status ;;
    logs)   shift; cmd_logs "$@" ;;
    seed)   cmd_seed ;;
    system) cmd_system ;;
    full)   cmd_full ;;
    "")
      echo "usage: $0 {up|down|status|logs <svc>|seed|system|full}" >&2
      exit 2
      ;;
    *)
      echo "unknown subcommand: $sub" >&2
      exit 2
      ;;
  esac
}

main "$@"
