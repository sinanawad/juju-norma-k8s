#!/bin/bash
# reproduce-destroy-model-hang.sh
#
# Reproduces intermittent destroy-model hang on K8s models (Juju 4.0.x).
# Requires: juju controller bootstrapped on microk8s
#
# Usage: ./reproduce-destroy-model-hang.sh

set -uo pipefail

JUJU="${JUJU_CLI:-juju}"
CONTROLLER="k8s"

for i in $(seq 1 17); do
    model="repro-$i"
    echo "=== iteration $i/17: $model ==="

    $JUJU add-model "$model" microk8s -c "$CONTROLLER"
    $JUJU deploy zinc-k8s -m "$model"
    sleep 5
    $JUJU status -m "$model"

    echo "destroying $model..."
    if timeout 240 $JUJU destroy-model "$model" --no-prompt --destroy-storage; then
        echo "OK: $model destroyed"
    else
        echo "HUNG: $model stuck in destroying"
        $JUJU models
        $JUJU destroy-model "$model" --no-prompt --destroy-storage --force --no-wait 2>/dev/null || true
        sleep 30
    fi
    echo ""
done
