ARG PYTHON_BASE_IMAGE=python:3.12-slim
FROM ${PYTHON_BASE_IMAGE}

ARG DEBIAN_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian
ARG DEBIAN_SECURITY_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian-security

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV APT_GET="apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30"

WORKDIR /opt/agentfactory

RUN set -eux; \
    for file in /etc/apt/sources.list /etc/apt/sources.list.d/*.sources; do \
        [ -f "$file" ] || continue; \
        sed -i \
            -e "s|http://deb.debian.org/debian-security|${DEBIAN_SECURITY_MIRROR}|g" \
            -e "s|https://deb.debian.org/debian-security|${DEBIAN_SECURITY_MIRROR}|g" \
            -e "s|http://deb.debian.org/debian|${DEBIAN_MIRROR}|g" \
            -e "s|https://deb.debian.org/debian|${DEBIAN_MIRROR}|g" \
            "$file"; \
    done

RUN $APT_GET update \
    && $APT_GET install -y --no-install-recommends \
        bash \
        ca-certificates \
        coreutils \
        curl \
        findutils \
        gawk \
        grep \
        procps \
        sed \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock README.md /opt/agentfactory/
RUN mkdir -p /opt/agentfactory/agent_factory \
    && touch /opt/agentfactory/agent_factory/__init__.py

RUN python -m pip install --upgrade pip uv \
    && uv export --frozen --no-dev --no-emit-project --format requirements-txt --output-file /tmp/requirements.txt \
    && uv pip install --system --require-hashes --requirements /tmp/requirements.txt \
    && python -m pip install --no-deps -e /opt/agentfactory

COPY agent_factory /opt/agentfactory/agent_factory

RUN python -c "from langgraph.checkpoint.sqlite import SqliteSaver; import tempfile; path = tempfile.NamedTemporaryFile(suffix='.sqlite').name; saver = SqliteSaver.from_conn_string(path); instance = saver.__enter__(); assert hasattr(instance.jsonplus_serde, 'dumps'), 'incompatible langgraph sqlite serializer'; saver.__exit__(None, None, None)"

CMD ["python", "-m", "agent_factory.agent_runtime_bridge.stdio_server"]
