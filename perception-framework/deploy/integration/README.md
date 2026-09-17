# Integration Infrastructure

This stack provides the real local services used by the integration tests:
Mosquitto on `127.0.0.1:1883`, single-node Kafka on `127.0.0.1:9092`, and
an OTLP collector on ports `4317`/`4318`.

```bash
mkdir -p deploy/integration/artifacts
docker compose -f deploy/integration/docker-compose.yml up -d
sudo cp /etc/rancher/k3s/k3s.yaml /tmp/aif-k3s.yaml
sudo chown "$(id -u):$(id -g)" /tmp/aif-k3s.yaml
KUBECONFIG=/tmp/aif-k3s.yaml \
AIF_OTEL_OUTPUT="$PWD/deploy/integration/artifacts/output.json" \
OPENCV_OPENCL_DEVICE=':CPU:' \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q -rs
docker compose -f deploy/integration/docker-compose.yml down
```

`OPENCV_OPENCL_DEVICE=':CPU:'` selects POCL when validating on a host without
a GPU OpenCL ICD. On Ubuntu it is provided by `pocl-opencl-icd`; this is a
validation fallback and does not claim GPU acceleration.

The configuration is intentionally development-only: MQTT and Kafka use
loopback-bound plaintext listeners. Production must supply TLS credentials,
broker ACLs, secrets, and non-default identities.
