#!/usr/bin/env bash
# =============================================================================
# File: e2e_stack.sh
# Version: 4
# Path: ay_platform_core/scripts/e2e_stack.sh
# Description: One-stop helper for the system-test stack.
#              Wraps `docker compose` + seed + `pytest tests/system/`.
#
#              v4: adds the `dev` subcommand for manual browser-driven
#              testing. `dev` layers `<monorepo>/.env.dev` on top of
#              `.env.test` (multiple --env-file, later overrides
#              earlier) and brings up the same compose stack with
#              the demo seed enabled (C2_DEMO_SEED_ENABLED=true) +
#              UX dev mode (C2_UX_DEV_MODE_ENABLED=true). The
#              tenant + 4 users + project + grants are seeded by
#              C2's lifespan ; no separate seed step needed.
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
#   ./ay_platform_core/scripts/e2e_stack.sh up        # build + start (test env)
#   ./ay_platform_core/scripts/e2e_stack.sh dev       # build + start (test+dev env, demo seed)
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

STACK_BASE_URL="${STACK_BASE_URL:-http://localhost:56000}"

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
  echo "    Public API:        $STACK_BASE_URL          # R-100-122 BASE+0"
  echo "    Traefik dashboard: http://localhost:56080   # R-100-122 BASE+80"
  echo "    Mock-LLM admin:    http://localhost:59800   # R-100-122 BASE+9800 (test only)"
  echo "    Observability:     http://localhost:59900   # R-100-122 BASE+9900 (test only)"
}

cmd_dev() {
  # Manual-test stack with demo seed + UX dev mode. Layers
  # `<monorepo>/.env.dev` on top of `.env.test` so the deltas live
  # in one tiny file (.env.dev = 2 flag flips). docker compose
  # supports multiple --env-file, later overrides earlier.
  _require_docker
  local dev_env="$MONOREPO_ROOT/.env.dev"
  if [[ ! -f "$dev_env" ]]; then
    echo "ERROR: $dev_env not found. Cannot start dev stack." >&2
    exit 1
  fi
  echo "==> Building images + starting DEV stack (demo seed enabled)"
  echo "    compose file: $COMPOSE_FILE"
  echo "    env files:    $ENV_FILE  +  $dev_env"
  docker compose \
    --env-file "$ENV_FILE" \
    --env-file "$dev_env" \
    -f "$COMPOSE_FILE" up -d --build
  echo "==> Demo seed will run on C2 startup ; ready in ~10-20s"
  echo "    Open: $STACK_BASE_URL    # login page surfaces 4 demo creds"
  echo ""
  echo "    Demo accounts (also visible on /login when stack is up) :"
  echo "      superroot       / dev-superroot   (tenant_manager super-root)"
  echo "      tenant-admin    / dev-tenant      (admin of tenant-test)"
  echo "      project-editor  / dev-editor      (editor on project-test)"
  echo "      project-viewer  / dev-viewer      (viewer on project-test)"
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
  # Invoke seed_e2e.py as a script (not via `python -m`) — `scripts/`
  # is intentionally NOT a Python package (no __init__.py: it mixes
  # bash + Python), so `python -m ay_platform_core.scripts.seed_e2e`
  # raises ModuleNotFoundError. Direct script invocation is the
  # contract.
  (cd "$AY_CORE" && \
    STACK_BASE_URL="$STACK_BASE_URL" \
    python scripts/seed_e2e.py --base-url "$STACK_BASE_URL")
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
    dev)    cmd_dev ;;
    down)   cmd_down ;;
    status) cmd_status ;;
    logs)   shift; cmd_logs "$@" ;;
    seed)   cmd_seed ;;
    system) cmd_system ;;
    full)   cmd_full ;;
    "")
      echo "usage: $0 {up|dev|down|status|logs <svc>|seed|system|full}" >&2
      exit 2
      ;;
    *)
      echo "unknown subcommand: $sub" >&2
      exit 2
      ;;
  esac
}

main "$@"
