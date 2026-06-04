#!/usr/bin/env bash
# Stop Picard desktop sidecars (use before curl-testing or reinstalling).
set -euo pipefail

pkill -f picard-desktop 2>/dev/null || true
pkill -f picard-supervisor 2>/dev/null || true
pkill -f picard-backend 2>/dev/null || true
pkill -f "node.*server.js" 2>/dev/null || true

for port in 3000 8000 13130; do
  pids=$(lsof -ti ":$port" 2>/dev/null || true)
  if [ -n "$pids" ]; then
    echo "Killing port $port: $pids"
    kill $pids 2>/dev/null || true
  fi
done

sleep 1
if lsof -i :3000 -i :8000 -i :13130 2>/dev/null; then
  echo "Warning: ports 3000/8000/13130 still in use (see above)." >&2
  exit 1
fi
echo "Ports 3000, 8000, and 13130 are free."
