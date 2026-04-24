# =============================================================================
# Dockerfile for Ubuntu Dev Environment
# Version: 1.6.0
# Path: .devcontainer/Dockerfile
# Description: Development container with Python 3.13, Node.js LTS, kubectl,
#              Claude Code CLI. Python 3.13 installed via deadsnakes PPA.
#
# Versions:
#   1.6.0: install all ay_platform_core dependencies (main + [test] + [dev])
#          from pyproject.toml at build time AGAINST the same path that is
#          bind-mounted at runtime (`/workspace/ay_platform_core`). pip
#          records a `.pth` pointing at `/workspace/ay_platform_core/src`;
#          the bind mount at container start replaces the content of that
#          directory with the host tree while the `.pth` entry stays valid,
#          so edits to the host source are picked up immediately without
#          re-running pip. No postCreateCommand swap needed.
#   1.5.0: first pyproject-driven install (installed to /opt/..., required
#          a postCreateCommand swap). Superseded by 1.6.0.
# =============================================================================

ARG TARGETOS=linux
ARG TARGETARCH=amd64
FROM --platform=${TARGETOS}/${TARGETARCH} ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Europe/Paris

USER root

# Base tooling + Python 3.13 via deadsnakes (single apt layer; no recommends)
# `libffi-dev` added so cryptography/argon2-cffi wheels can build if needed.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl wget git nano unzip ca-certificates gnupg lsb-release \
    net-tools iputils-ping telnet \
    software-properties-common build-essential libffi-dev \
    sudo jq file \
    python3-pip python3-venv \
 && add-apt-repository ppa:deadsnakes/ppa -y \
 && apt-get update && apt-get install -y --no-install-recommends \
    python3.13 python3.13-venv python3.13-dev \
 && apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Install kubectl (latest stable)
RUN curl -LO "https://dl.k8s.io/release/$(curl -Ls https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" \
 && chmod +x kubectl && mv kubectl /usr/local/bin/

# Install Node.js (latest LTS) - required for Claude Code CLI
RUN curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

# Make Python 3.13 the default for python3 and python
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.13 2 \
 && update-alternatives --install /usr/bin/python  python  /usr/bin/python3.13 2

# Ensure pip is for Python 3.13
RUN curl -sS https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py \
 && python3.13 /tmp/get-pip.py \
 && rm -f /tmp/get-pip.py

# Claude Code CLI (Node) + latest pip/setuptools/wheel.
RUN npm install -g @anthropic-ai/claude-code \
 && python3.13 -m pip install --upgrade --no-cache-dir pip setuptools wheel

# -----------------------------------------------------------------------------
# ay_platform_core build-time install.
# Build context is the monorepo root (see devcontainer.json `context: ".."`),
# so we can COPY `ay_platform_core/` directly. The copy goes to the SAME
# path that is bind-mounted at runtime (`/workspace/ay_platform_core`) so
# the `.pth` file written by `pip install -e` keeps pointing to a valid
# location after the mount — the directory CONTENTS change (build-time
# snapshot → live host source), but `/workspace/ay_platform_core/src`
# still resolves, and Python reads the live code.
# Installs: main `dependencies` + [test] + [dev] via the `all` extra.
# -----------------------------------------------------------------------------
COPY ay_platform_core/pyproject.toml /workspace/ay_platform_core/pyproject.toml
COPY ay_platform_core/src /workspace/ay_platform_core/src
RUN python3.13 -m pip install --no-cache-dir -e '/workspace/ay_platform_core[all]'

# Docker group (GID will be re-aligned at container start by postCreateCommand)
RUN getent group docker || groupadd -g 999 docker

# Non-root developer user
RUN useradd -m -s /bin/bash developer \
 && usermod -aG sudo developer \
 && usermod -aG docker developer \
 && echo "developer ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

USER developer
WORKDIR /workspace

CMD ["/bin/bash"]
