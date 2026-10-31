# Parent Recap on the NAS: the program, its own Node, the wilma CLI it drives, and the Codex CLI
# that writes the Brief. Debian slim + Node 22, so nothing depends on the NAS's own toolchain.
FROM node:22-bookworm-slim

# PARENT_RECAP_OWN_SERVER hands the setup page every step rather than the gateway alone; the
# container says so too: entrypoint.sh keeps the evening job, so there is no timer to install and
# nothing to find where a Linux install would be (jobs_linux, setup_status, finish).
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    TZ=Europe/Helsinki \
    HOME=/root \
    PATH=/opt/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    PARENT_RECAP_OWN_SERVER=1 \
    PARENT_RECAP_CONTAINER=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      python3 python3-venv ca-certificates tzdata procps \
 && rm -rf /var/lib/apt/lists/* \
 && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo "$TZ" > /etc/timezone

# The program's Python, with the pinned dependencies from app/pyproject.toml
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir --upgrade pip

COPY app /opt/parent-recap/app
RUN /opt/venv/bin/pip install --no-cache-dir /opt/parent-recap/app \
 && /opt/venv/bin/python -c "import family_brief, importlib.metadata as m; print('family-brief', m.version('family-brief'))"

# Parent Recap's own Node, in the place own_node() looks for it (runtime/node-v*/bin/node), and the
# wilma CLI npm installs into its own prefix as a global install, which puts the package in
# lib/node_modules and the launcher in bin/wilma — the layout own_node() reads on Linux.
RUN mkdir -p /root/ParentRecap/runtime/node-v22/bin \
 && ln -sf "$(command -v node)" /root/ParentRecap/runtime/node-v22/bin/node \
 && npm install -g --prefix /root/ParentRecap/wilma --no-audit --no-fund @wilm-ai/wilma-cli \
 && test -x /root/ParentRecap/wilma/bin/wilma \
 && /root/ParentRecap/runtime/node-v22/bin/node /root/ParentRecap/wilma/bin/wilma --version

# The Linked Device's Baileys tree, in the place baileys_install() checks: the package files are
# the pinned ones, and npm installs exactly what they lock, so up_to_date() says yes.
RUN mkdir -p /root/ParentRecap/baileys \
 && cp /opt/parent-recap/app/src/family_brief/baileys/package.json \
       /opt/parent-recap/app/src/family_brief/baileys/package-lock.json /root/ParentRecap/baileys/ \
 && cd /root/ParentRecap/baileys \
 && npm ci --ignore-scripts --no-audit --no-fund \
 && npm ls @whiskeysockets/baileys

# Codex, which writes the Brief on the ChatGPT sign-in in ~/.codex
RUN npm install -g --no-audit --no-fund @openai/codex && codex --version

COPY nas/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY nas/follow.py /usr/local/bin/parent-recap-follow
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/parent-recap-follow

WORKDIR /root
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
