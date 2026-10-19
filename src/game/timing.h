/* SPDX-License-Identifier: MIT
 * Hooks for opt-in, bounded per-dispatch GPU timestamps, a diagnostic build option never used for scored FPS trials.
 * Builds without it, every release build among them, compile the empty hooks at the end of this file.
 */
static void game_timing_prepare(ID3D12Device*d){(void)d;}
static void game_timing_present(void){}
static void game_timing_dump(void){}
static void game_timing_release(void){}
