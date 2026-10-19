#!/bin/sh
# SPDX-License-Identifier: MIT
set -eu
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ "$#" -eq 0 ]; then
    echo 'Use this script as the game wrapper; it needs the game command.' >&2
    exit 2
fi
# MFG_WINE_OVERRIDE
# The addon finds its verified shaders beside itself, independently of game CWD.
unset XEFG_GAME_PROFILE BC250_XEFG_OWNER_MODULE
if [ -f "$base/../OptiScaler/plugins/BC250-XeFG/shaders/mfg-frame-settings.required" ]; then
    # The addon reads the shared INI. Only an explicit launch override wins.
    unset XEFG_FLOW_CAP
    if [ "${BC250_XEFG_FRAME_CAP+x}" = x ]; then
        case "$BC250_XEFG_FRAME_CAP" in
            0|1) export XEFG_FLOW_CAP="$BC250_XEFG_FRAME_CAP" ;;
            *) echo 'BC250_XEFG_FRAME_CAP must be 0 or 1; remove it to use saved settings.' >&2; exit 2 ;;
        esac
    fi
else
    # Compatibility with the prior tester addon, whose wrapper owns FrameCap.
    saved_cap=1
    if [ -f "$base/settings.ini" ]; then
        saved_cap=$(sed -n 's/^FrameCap=\([01]\)\r\{0,1\}$/\1/p' "$base/settings.ini")
        case "$saved_cap" in 0|1) ;; *) echo 'Invalid FrameCap setting.' >&2; exit 2 ;; esac
    fi
    export BC250_XEFG_FRAME_CAP="${BC250_XEFG_FRAME_CAP:-$saved_cap}"
    export XEFG_FLOW_CAP="$BC250_XEFG_FRAME_CAP"
fi
if [ "${BC250_XEFG_DISABLE:-0}" != 1 ]; then
    if [ "${BC250_XEFG_NO_STAGGERED_SUBMIT:-1}" = 1 ]; then
        case ",${VKD3D_CONFIG:-}," in
            *,no_staggered_submit,*) ;;
            *) export VKD3D_CONFIG="${VKD3D_CONFIG:+$VKD3D_CONFIG,}no_staggered_submit" ;;
        esac
    fi
    export VK_LAYER_PATH="$base/layer${VK_LAYER_PATH:+:$VK_LAYER_PATH}"
    export VK_INSTANCE_LAYERS="VK_LAYER_BC250_xefg_wave${VK_INSTANCE_LAYERS:+:$VK_INSTANCE_LAYERS}"
    export XEFG_WAVE_CONFIG="$base/../OptiScaler/plugins/BC250-XeFG/shaders/waves.txt"
fi
exec "$@"
