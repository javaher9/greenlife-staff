"""Exercise the production shell's failure paths without Docker or a server."""

from pathlib import Path
import os
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("deploy_runner.sh").read_text()
BIND_FUNCTIONS = "verify_nginx_bind_mount() {" + SCRIPT.split(
    "verify_nginx_bind_mount() {", 1
)[1].split("# Source sync can replace", 1)[0]
CLEANUP = SCRIPT.split("CANDIDATE_TRAFFIC_POSSIBLE=0\n", 1)[1].split(
    "\ndocker image inspect", 1
)[0]
COLLISION_CHECK = "for candidate_name in " + SCRIPT.split(
    "for candidate_name in ", 1
)[1].split("# Set before attempting any proxy switch", 1)[0]
NGINX_FUNCTIONS = "nginx_worker_pids() {" + SCRIPT.split(
    "nginx_worker_pids() {", 1
)[1].split("probe_public_proxy() {", 1)[0]
CUTOVER = SCRIPT.split(
    'echo "Gracefully switching public traffic to the healthy candidate..."', 1
)[1].split("# A dedicated lightweight worker", 1)[0]
DATABASE = SCRIPT.split(
    'if "${COMPOSE[@]}" config --services | grep -qx db; then', 1
)[1].split("# Summarize the outgoing web container", 1)[0]
DATABASE = 'if "${COMPOSE[@]}" config --services | grep -qx db; then' + DATABASE


MOCKS = r"""
set -Eeuo pipefail
declare -A calls
PUBLIC_CANDIDATE=public-candidate
LAN_CANDIDATE=lan-candidate
PUBLIC_WEB=public-stable
LAN_WEB=lan-stable
PUBLIC_NGINX=public-proxy
LAN_NGINX=lan-proxy
CANDIDATE_TRAFFIC_POSSIBLE=0
DEPLOY_PATH=/mock-runtime
record() {
  local key="$*"
  calls["$key"]=$(( ${calls["$key"]:-0} + 1 ))
  printf 'CALL %s %s\n' "$key" "${calls["$key"]}"
  [[ "${FAIL_AT:-}" != "$key:${calls["$key"]}" ]]
}
docker() {
  if [[ "$1" == ps ]]; then
    if [[ "${LAN_PRESENT:-1}" == 1 ]]; then
      printf '%s\n' "$LAN_WEB" "$LAN_CANDIDATE"
    fi
    return 0
  fi
  printf '%s\n' "$*" >> "$MOCK_CALL_FILE"
  record docker "$@"
}
compose() {
  if [[ "$1" == config ]]; then
    printf 'db\nweb\n'
    if [[ "${LAN_PRESENT:-1}" == 1 ]]; then printf 'web_lan\n'; fi
    return 0
  fi
  record compose "$@"
}
COMPOSE=(compose)
set_public_upstream() { record set_public_upstream "$@"; }
set_lan_upstream() { record set_lan_upstream "$@"; }
reload_public_nginx() { record reload_public_nginx; }
reload_lan_nginx() { record reload_lan_nginx; }
probe_public_proxy() { record probe_public_proxy "$@"; }
probe_lan_proxy() { record probe_lan_proxy "$@"; }
probe_candidate() { record probe_candidate "$@"; }
"""

NGINX_MOCK = r"""
verify_nginx_config_visible() { return 0; }
docker() {
  printf '%s\n' "$*" >> "$MOCK_CALL_FILE"
  if [[ "$*" == 'exec public-proxy ps -o pid,args' ]]; then
    count=$(grep -c 'ps -o pid,args' "$MOCK_CALL_FILE")
    if [[ "$SCENARIO" == ps_failure && "$count" -gt 1 ]]; then return 1; fi
    printf 'PID COMMAND\n1 nginx: master process nginx -g daemon off;\n'
    if [[ "$SCENARIO" == no_workers ]]; then return 0; fi
    if [[ "$SCENARIO" == timeout || "$count" -le 2 ]]; then
      printf '11 nginx: worker process\n'
    elif [[ "$count" == 3 ]]; then
      printf '11 nginx: worker process is shutting down\n22 nginx: worker process\n'
    else
      printf '22 nginx: worker process\n'
    fi
    return 0
  fi
  if [[ "$SCENARIO" == reload_failure && "$*" == 'exec public-proxy nginx -s reload' ]]; then
    return 1
  fi
  return 0
}
sleep() { printf 'SLEEP %s\n' "$*" >> "$MOCK_CALL_FILE"; }
"""

BIND_MOCK = r"""
set -Eeuo pipefail
docker() {
  printf '%s\n' "$*" >> "$MOCK_CALL_FILE"
  if [[ "$1" == ps ]]; then
    if [[ "${MOUNT_MODE:-}" == docker_error ]]; then return 1; fi
    printf 'greenlife-staff-runtime-nginx-1\n'
    return 0
  fi
  if [[ "$3" == stat ]]; then
    if [[ "${MOUNT_MODE:-}" == stat_error ]]; then return 1; fi
    if [[ "${MOUNT_MODE:-}" == content_mismatch ]]; then
      stat -c "$5" "$DEPLOY_PATH/deploy/nginx.conf"
    else
      stat -c "$5" "$MOUNT_PATH"
    fi
    return
  fi
  if [[ "$3" == sha256sum ]]; then
    sha256sum "$MOUNT_PATH"
    return
  fi
  return 0
}
"""


class DeploymentSafetyTests(unittest.TestCase):
    def run_shell(self, body, extra_env=None):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "mock-calls"
            result = subprocess.run(
                ["bash", "-c", body], capture_output=True, text=True, timeout=5,
                env={**os.environ, **(extra_env or {}), "MOCK_CALL_FILE": str(log)},
            )
            result.mock_calls = log.read_text() if log.exists() else ""
            return result

    def run_mount_fixture(self, mode, body):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "deploy").mkdir()
            source = root / "deploy/nginx.conf"
            source.write_text("set $greenlife_web_upstream web:8005;\n")
            mounted = root / "mounted-default.conf"
            os.link(source, mounted)
            if mode in ("replacement", "content_mismatch"):
                replacement = root / "new.conf"
                # Identical contents still constitute a stale inode: later
                # candidate edits would no longer reach the mounted file.
                replacement.write_text(source.read_text())
                os.replace(replacement, source)
                if mode == "content_mismatch":
                    source.write_text("set $greenlife_web_upstream candidate:8005;\n")
            return self.run_shell(body, {
                "DEPLOY_PATH": str(root), "MOUNT_PATH": str(mounted),
                "MOUNT_MODE": mode,
            })

    def test_current_file_mount_passes_readonly_preflight(self):
        result = self.run_mount_fixture(
            "matching", BIND_MOCK + BIND_FUNCTIONS
            + '\ncheck_running_nginx_bind_mounts\necho PREFLIGHT_PASSED\n'
            + 'verify_nginx_config_visible greenlife-staff-runtime-nginx-1 "$DEPLOY_PATH/deploy/nginx.conf"\n'
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PREFLIGHT_PASSED", result.stdout)
        self.assertNotIn("nginx -s reload", result.mock_calls)

    def test_replaced_inode_or_inspection_error_stops_before_runtime_changes(self):
        for mode in ("replacement", "stat_error", "docker_error"):
            with self.subTest(mode=mode):
                result = self.run_mount_fixture(
                    mode, BIND_MOCK + BIND_FUNCTIONS
                    + '\ncheck_running_nginx_bind_mounts\necho RUNTIME_MUTATION\n'
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("RUNTIME_MUTATION", result.stdout)
                self.assertNotIn("nginx -s reload", result.mock_calls)
                if mode == "replacement":
                    self.assertIn("stale nginx config bind mount", result.stderr)
        self.assertLess(
            SCRIPT.index("\ncheck_running_nginx_bind_mounts\n"),
            SCRIPT.index('python3 "$DEPLOY_PATH/scripts/harden_env.py"'),
        )

    def test_container_content_mismatch_blocks_reload(self):
        result = self.run_mount_fixture(
            "content_mismatch", BIND_MOCK + BIND_FUNCTIONS + NGINX_FUNCTIONS
            + '\nreload_nginx_safely greenlife-staff-runtime-nginx-1 "$DEPLOY_PATH/deploy/nginx.conf"\n'
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot see the intended upstream config", result.stderr)
        self.assertNotIn("nginx -t", result.mock_calls)
        self.assertNotIn("nginx -s reload", result.mock_calls)

    def test_cleanup_before_cutover_removes_unused_candidates(self):
        result = self.run_shell(MOCKS + CLEANUP + "\nexit 9\n")
        self.assertEqual(result.returncode, 9)
        self.assertNotIn("Preserving candidate", result.stderr)
        self.assertIn("rm -f public-candidate lan-candidate", result.mock_calls)

    def test_post_cutover_failures_preserve_candidate(self):
        failures = [
            "set_public_upstream public-candidate:1",
            "reload_public_nginx:1",
            "reload_lan_nginx:1",
            "probe_public_proxy 15:1",
            "compose up -d --no-deps --no-build --force-recreate web:1",
            "compose up -d --no-deps --no-build --force-recreate web_lan:1",
            "probe_candidate public-proxy public-stable staff.greenlifeclinics.com:1",
            "probe_candidate lan-proxy lan-stable 192.168.40.96:1",
            "reload_public_nginx:2",
            "reload_lan_nginx:2",
            "probe_public_proxy 20:1",
            "probe_lan_proxy 20:1",
        ]
        for failure in failures:
            with self.subTest(failure=failure):
                result = self.run_shell(
                    MOCKS + f"\nFAIL_AT='{failure}'\n" + CLEANUP + CUTOVER
                )
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn("Preserving candidate containers", result.stderr)
                self.assertNotIn("rm -f", result.mock_calls)

    def test_success_releases_cleanup_guard_only_after_stable_health(self):
        for lan_present in (0, 1):
            with self.subTest(lan_present=lan_present):
                result = self.run_shell(
                    MOCKS + f"\nLAN_PRESENT={lan_present}\n" + CLEANUP + CUTOVER
                    + '\n[[ "$CANDIDATE_TRAFFIC_POSSIBLE" == 0 ]]\n'
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn("Preserving candidate", result.stderr)
                self.assertIn("rm -f public-candidate lan-candidate", result.mock_calls)
                self.assertIn("probe_public_proxy 20", result.stdout)
                if lan_present:
                    self.assertIn("probe_lan_proxy 20", result.stdout)

    def test_nginx_reload_waits_for_original_workers_even_before_shutdown_title(self):
        result = self.run_shell(
            MOCKS + '\nSCENARIO=success\n' + NGINX_MOCK + CLEANUP
            + NGINX_FUNCTIONS + '\nCANDIDATE_TRAFFIC_POSSIBLE=1\n'
            + 'reload_public_nginx\nCANDIDATE_TRAFFIC_POSSIBLE=0\n'
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.mock_calls.count("ps -o pid,args"), 4)
        self.assertEqual(result.mock_calls.count("SLEEP 2"), 2)
        self.assertIn("Old nginx workers drained: public-proxy", result.stdout)
        self.assertIn("rm -f public-candidate lan-candidate", result.mock_calls)

    def test_nginx_drain_timeout_or_inspection_failure_preserves_candidates(self):
        for scenario in ("timeout", "ps_failure", "no_workers", "reload_failure"):
            with self.subTest(scenario=scenario):
                result = self.run_shell(
                    MOCKS + f'\nSCENARIO={scenario}\n' + NGINX_MOCK + CLEANUP
                    + NGINX_FUNCTIONS + '\nCANDIDATE_TRAFFIC_POSSIBLE=1\n'
                    + 'reload_public_nginx\nCANDIDATE_TRAFFIC_POSSIBLE=0\n'
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Preserving candidate containers", result.stderr)
                self.assertNotIn("rm -f", result.mock_calls)
                if scenario == "timeout":
                    self.assertIn("did not drain within 120 seconds", result.stderr)
                    self.assertEqual(result.mock_calls.count("SLEEP 2"), 60)

    def test_retry_name_collision_never_removes_existing_candidate(self):
        result = self.run_shell(MOCKS + COLLISION_CHECK + CLEANUP)
        self.assertEqual(result.returncode, 1)
        self.assertIn("candidate name already exists", result.stderr)
        self.assertNotIn("rm -f", result.mock_calls)

    def test_unready_database_aborts_without_restart_or_recreation(self):
        mocks = r"""
set -Eeuo pipefail
compose() {
  if [[ "$1" == config ]]; then echo db; return 0; fi
  if [[ "$1" == exec ]]; then return 1; fi
  printf 'CALL %s\n' "$*"
}
COMPOSE=(compose)
sleep() { :; }
"""
        result = self.run_shell(mocks + DATABASE)
        self.assertEqual(result.returncode, 1)
        self.assertIn("up -d --no-recreate db", result.stdout)
        self.assertNotIn("CALL restart", result.stdout)
        self.assertIn("aborting release without restarting", result.stderr)


if __name__ == "__main__":
    unittest.main()
