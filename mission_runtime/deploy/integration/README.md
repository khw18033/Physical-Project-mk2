# Integration Infrastructure

This stack provides the real local services used by the integration tests:
Mosquitto on `127.0.0.1:1883`, single-node Kafka on `127.0.0.1:9092`, an OTLP
collector on ports `4317`/`4318`, and Prometheus on `127.0.0.1:9090`.

Prometheus scrapes the collector's own Prometheus exporter (`:8889`), so a metric
exported over OTLP really becomes a scraped series that
`providers/observability_query.py` can query back — the same two hops the zone
edge makes. `tests/test_real_prometheus_path.py` walks that round trip and skips
cleanly when the stack is down. Collector version, scrape intervals,
`metric_expiration` and retention are copied from the integration repository's
edge stack rather than chosen here; the values and their sources are recorded in
`integration/deployment_topology.py` (§관측) and pinned by
`tests/test_deployment_topology.py`.

Prometheus here stands in for the **zone edge**, which is where the detail lives
(AI-O-01, 원칙 #14). Central only pulls a summary over `/federate`, and that
`match[]` does not select our metric names today — see
`docs/integration-handover.md` §1-나.

Shortest path (from the project root): `make up`, `make check`, `make down` —
see the Makefile header for `label` / `smoke` / `bootstrap` / `ui`. `make up` also
fixes the ownership of `artifacts/` (otelcol runs as uid 10001; a root-owned dir
puts the collector in a restart loop). Bind to a routable address for terminals
with `AIF_BIND=<ip> AIF_ADVERTISE=<ip> make up` (plaintext; no TLS/ACL here).

Manual equivalent:

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
