#!/usr/bin/env bash
# Source this file. Validate before evaluating the fixed channel values.
_channel_values="$(python3 "$(dirname "${BASH_SOURCE[0]}")/channels.py")" || return 2
eval "${_channel_values}"
unset _channel_values
