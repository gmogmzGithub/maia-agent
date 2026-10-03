#!/bin/sh
set -eu

umask 077
mkdir -p /var/lib/garage/meta /var/lib/garage/data

cat > /etc/garage.toml <<EOF
metadata_dir = "/var/lib/garage/meta"
data_dir = "/var/lib/garage/data"
db_engine = "sqlite"
replication_factor = 1
rpc_bind_addr = "[::]:3901"
rpc_public_addr = "127.0.0.1:3901"
rpc_secret = "${GARAGE_RPC_SECRET}"

[s3_api]
s3_region = "us-east-1"
api_bind_addr = "[::]:3900"
root_domain = ".s3.garage.localhost"

[admin]
api_bind_addr = "127.0.0.1:3903"
admin_token = "${GARAGE_ADMIN_TOKEN}"
metrics_token = "${GARAGE_METRICS_TOKEN}"
EOF
chmod 0600 /etc/garage.toml

/garage server --single-node &
server_pid=$!
stop_server() {
    kill -TERM "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
}
trap stop_server INT TERM

ready=false
for _ in $(seq 1 60); do
    if /garage status >/dev/null 2>&1; then
        ready=true
        break
    fi
    if ! kill -0 "$server_pid" 2>/dev/null; then
        wait "$server_pid"
    fi
    sleep 1
done
if [ "$ready" != true ]; then
    echo "Garage did not become ready in 60 seconds." >&2
    exit 1
fi

ensure_bucket() {
    bucket=$1
    if ! /garage bucket info "$bucket" >/dev/null 2>&1; then
        /garage bucket create "$bucket"
    fi
    /garage bucket deny --owner "$bucket" --key "$PRODUCT_ACCESS_KEY" >/dev/null 2>&1 || true
    /garage bucket allow --read --write "$bucket" --key "$PRODUCT_ACCESS_KEY"
}

if ! /garage key info "$PRODUCT_ACCESS_KEY" >/dev/null 2>&1; then
    /garage key import --yes -n maia-product "$PRODUCT_ACCESS_KEY" "$PRODUCT_SECRET_KEY"
fi

ensure_bucket maia-listing-media
ensure_bucket maia-listing-renditions

wait "$server_pid"
