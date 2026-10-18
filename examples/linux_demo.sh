#!/bin/bash
# Linux Bash Script for Operator OS
echo "=========================================="
echo "[LINUX/WSL] Executing bash script inside Operator OS"
echo "Host Kernel: $(uname -s -r -m 2>/dev/null || echo 'Linux Emulation')"
echo "Timestamp:   $(date)"
echo "Memory Available:"
free -m 2>/dev/null || echo "MemTotal: 4096 MB (Subsystem Assigned)"
echo "=========================================="
