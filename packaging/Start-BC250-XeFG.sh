#!/bin/sh
# SPDX-License-Identifier: MIT
set -eu
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$base/setup.py"
