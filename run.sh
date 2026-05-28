#!/bin/bash
cd "$(dirname "$0")"
exec /home/bruce/.hermes/hermes-agent/venv/bin/python3 server.py 8090
