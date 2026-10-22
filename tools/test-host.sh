#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../device"
test_dir="$(mktemp -d /tmp/voice-app-tests.XXXXXX)"
trap 'rm -rf -- "$test_dir"' EXIT
"${CC:-cc}" -std=c11 -Wall -Wextra -Werror -Imain tests/test_app_state.c main/apps/voice/app_state.c -o "$test_dir/state"
"$test_dir/state"
"${CC:-cc}" -std=c11 -Wall -Wextra -Werror -Imain tests/test_emo_map.c main/apps/voice/emo_map.c -o "$test_dir/emo"
"$test_dir/emo"
"${CC:-cc}" -std=c11 -Wall -Wextra -Werror -Imain/apps/voice tests/test_ui_pixel_math.c main/apps/voice/ui_pixel_math.c -o "$test_dir/math"
"$test_dir/math"
echo 'Voice application-only host tests: PASS'
