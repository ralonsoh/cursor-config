---
name: devstack-debug
description: >-
  Known issues and fixes for DevStack stack.sh/unstack.sh failures on the
  remote-vm VMs, collected from real debugging sessions. Use when
  stack.sh hangs or fails, a devstack service does not start, or when
  re-stacking after interrupted runs.
---

# DevStack Debug

Collection of real issues found while stacking/unstacking DevStack on the
remote-vm VMs (Ubuntu, OVN backend, virtiofs-shared `/opt/stack`). Each
entry: symptom → root cause → fix. Check the failed stack log
(`/opt/stack/logs/screen/xstack.sh.log.*` or the `tee`d run log) to match
the symptom, then apply the fix and re-stack.

## Where to look first

- Last summary: `ls -lt /opt/stack/logs/screen/`, then the newest
  `xstack.sh.log.*` — the `[ERROR]` line names the lib and line that died
  (e.g. `lib/keystone:517 keystone did not start`).
- Async phase failures (init_placement, init_cinder, ...) log to
  `/opt/stack/async/<name>.log`, NOT to the main log.
- Service logs: `sudo journalctl -u devstack@<service>`.
- Apache fronts port 80 and proxies every API
  (`/identity`, `/placement`, `/compute`, ...) — if ALL endpoints fail at
  once, suspect apache, not the individual services.

## 1. stack.sh hangs forever in init_placement (no error, just timeout)

**Symptom:** log ends at `async_wait init_placement` / `Signaling child to
exit`, exit trap fires ~6 minutes later. A `ps` shows a stuck
`openstack user create placement` process.

**Root cause:** Apache (Horizon) workers crash-looping:
`mod_wsgi: Unable to stat Python home <venv>` →
`Failed to import encodings module` → segfault every second. Apache
wedged → port 80 dead → every keystone call hangs → placement init (which
creates a keystone user) never returns.

**Causes seen for the unreachable venv:**
- `/home/stack` mode 750 (the overridden `DATA_DIR=/home/stack/data`
  lives under the home): `www-data` cannot traverse. Fix:
  `chmod 755 /home/stack`.
- Stale `WSGIPythonHome` in `/etc/apache2/sites-available/horizon.conf`
  pointing at a deleted venv (after removing a DATA_DIR): fix the path
  and `sudo systemctl restart apache2`.
- Share root not traversable with the default `DATA_DIR=/opt/stack/data`
  (venv on the virtiofs share): `/opt/stack` was `drwxrwxr--` — others
  lack the `x` bit. Fix ON THE HOST: `chmod o+x /opt/stack`.

**Verify:** `sudo -u www-data ls <venv>/bin/python` must work, then
`curl -o /dev/null -w '%{http_code}' http://127.0.0.1/identity/v3` → 200.
Also kill the stuck `openstack ... placement` process before re-stacking.

## 2. cinder-volume dies: FileNotFoundError 'cinder-rtstool'

**Symptom:** `No volume service(s) started successfully, terminating`;
journal shows `FileNotFoundError: ... 'cinder-rtstool'`.

**Root cause:** with `GLOBAL_VENV=True`, `stack.sh` unconditionally
symlinks `/opt/stack/data/venv/bin/{cinder-rtstool,cinder-manage,glance,
nova-manage,openstack}` into `/usr/local/bin`, HARDCODING the default
DATA_DIR path. If `DATA_DIR` is overridden in local.conf (on these VMs:
`/home/stack/data`), those links dangle; `sudo cinder-rtstool`
(resolve via sudo secure_path) fails with FileNotFoundError.

**Fix:** `sudo ln -sfn <DATA_DIR> /opt/stack/data` (compat symlink), then
`cinder-rtstool verify` must succeed. With the default DATA_DIR this
cannot happen.

## 3. g-api did not start after a failed first run (stale process)

**Symptom:** re-stack fails `g-api did not start`; glance healthy on its
direct port but apache `/image` returns 503.

**Root cause:** devstack picks a fresh random port for the glance uwsgi
http-socket on each run. The old glance-api from a previous (failed) run
is still running on the OLD port; `run_process g-api` →
`systemctl start` does not restart an already-active unit, so apache
proxies to the new port while glance listens on the old one.

**Fix:** clean up leftover state before re-stacking:
`./unstack.sh --all` (or at least `sudo systemctl stop devstack@g-api`).

## 4. Tempest verify-config: "is not a tempest command"

**Symptom:** stack.sh fails at the very last step:
`tempest: 'verify-config -uro ...' is not a tempest command`.

**Root cause:** tempest checkout is older (41.0.0 / 2024.2 era) but its
tox venv installs unconstrained oslo.utils (10.x), where `md5` was removed
from `oslo_utils.secretutils`. The entry-point import fails, cliff drops
the subcommand, and the error message misleadingly blames the command
name.

**Fix** (patch the checkout like upstream later did):

```bash
cd /opt/stack/tempest && sed -i \
  's/^from oslo_utils.secretutils import md5$/from hashlib import md5/' \
  tempest/lib/common/preprov_creds.py tempest/lib/common/ssh.py \
  tempest/api/object_storage/test_object_services.py \
  tempest/api/object_storage/test_object_slo.py \
  tempest/tests/lib/common/test_preprov_creds.py
```

Note: a re-stack that rebuilds `.tox` may revert the venv part; re-run
`pip install -r requirements.txt --no-deps && pip install -e . --no-deps`
in `.tox/tempest` if the binary is missing. If a failed `tox` invocation
clobbered the venv, reinstalling tempest into it (`pip install --no-deps
-e .`) restores the entry points.

## 5. Re-stack did not actually start (silent no-op)

**Symptom:** command sent to tmux but no new stack.sh process, log file
unchanged — especially after a previous run's exit trap.

**Cause:** keystrokes landed while the pane was still in the exit-trap
subshell; the command sits at the prompt unexecuted.

**Fix:** verify with `ps -ef | grep '[.]/stack.sh'` and check the log's
mtime before waiting; re-send Enter if needed. Always confirm the run
actually started before monitoring.

## 6. Encodings error running a venv python on the share

**Symptom:** `Fatal Python error: init_fs_encoding ... ModuleNotFoundError:
No module named 'encodings'` from a python under `/opt/stack`.

**Root cause:** the venv was built by a different OS side of the
virtiofs share (host python 3.8 vs guest 3.14): the interpreter binary
resolves its stdlib against a `sys.prefix` that does not exist on this
side.

**Fix:** delete the venv and rebuild it from the side that will use it.
Remember venvs on the shared directory are single-OS: never build on the
host and run in the guest (or vice versa).

## 7. Boot hangs 2 minutes in systemd-networkd-wait-online

Not a stack.sh failure but hits the same VMs: an interface with no
routable config (e.g. second NIC, dhcp disabled, nothing else) stays
`degraded (configuring)` forever; wait-online blocks the boot for its
2-minute timeout. Fix in netplan: `optional: true` on that interface
(generates `RequiredForOnline=no`).
