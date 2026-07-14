ARG ROCM_RUNTIME_BASE_IMAGE
FROM ${ROCM_RUNTIME_BASE_IMAGE}

ARG PYPI_INDEX_URL

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PIP_INDEX_URL=${PYPI_INDEX_URL}

WORKDIR /opt/agentfactory

COPY pyproject.toml uv.lock README.md /opt/agentfactory/
COPY agent_factory /opt/agentfactory/agent_factory

RUN python -m pip install --no-cache-dir -e /opt/agentfactory \
    && python -m pip install --no-cache-dir "sentence-transformers>=3,<6" "transformers>=4.51,<6" \
    && python -c "import torch; assert torch.version.hip, 'ROCm PyTorch build is required'" \
    && python -c "import vllm; import sentence_transformers"

CMD ["python", "-m", "agent_factory.local_inference.run_vllm", "--help"]
