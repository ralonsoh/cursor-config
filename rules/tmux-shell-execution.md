---
description: Execute all shell commands inside a tmux session so the user can watch in real time
alwaysApply: true
---

# Shell Execution via tmux

All shell commands — local and remote (VMs via SSH) — MUST run inside a tmux
session named **cursor** so the user can `tmux attach -t cursor` and observe.

## Pattern

Use the Shell tool with this template:

```bash
rm -f /tmp/.cursor-out
tmux has-session -t cursor 2>/dev/null || tmux new-session -d -s cursor
tmux send-keys -t cursor '<COMMAND> 2>&1 | tee /tmp/.cursor-out; echo __CURSOR_DONE__ >> /tmp/.cursor-out' Enter
for i in $(seq 1 300); do grep -q __CURSOR_DONE__ /tmp/.cursor-out 2>/dev/null && break; sleep 1; done
cat /tmp/.cursor-out
```

- Replace `<COMMAND>` with the actual command. Escape inner single quotes
  (`'\''`) or use double-quote wrapping when needed.
- Adjust the `seq 1 300` upper bound to match the expected runtime (default 5 min).
- Set the Shell tool `block_until_ms` to slightly above that same timeout.

## Remote VM commands

Remote commands run inside a tmux session **on the VM itself**, not on the host.
SSH into the VM, ensure a tmux session named `cursor` exists there, send the
command via `send-keys`, and capture output — all in one SSH invocation.

```bash
rm -f /tmp/.cursor-vm-out
sshpass -p '***' ssh -o StrictHostKeyChecking=no user@host bash -s <<'REMOTE_SCRIPT' 2>&1 | tee /tmp/.cursor-vm-out
tmux has-session -t cursor 2>/dev/null || tmux new-session -d -s cursor
rm -f /tmp/.cursor-out
tmux send-keys -t cursor '<REMOTE_COMMAND> 2>&1 | tee /tmp/.cursor-out; echo __CURSOR_DONE__ >> /tmp/.cursor-out' Enter
for i in $(seq 1 300); do grep -q __CURSOR_DONE__ /tmp/.cursor-out 2>/dev/null && break; sleep 1; done
cat /tmp/.cursor-out
REMOTE_SCRIPT
cat /tmp/.cursor-vm-out
```

- The user can SSH into the VM and run `tmux attach -t cursor` to watch live.
- Replace `<REMOTE_COMMAND>` with the actual command to run on the VM.
- Adjust `seq 1 300` and `block_until_ms` to match expected runtime.
- This pattern does NOT use the host tmux session; the host Shell tool runs
  the SSH command directly.

## Rules

- NEVER run shell commands directly; always go through the tmux session.
- If the tmux session already exists, reuse it (do not kill/recreate).
- For fast commands (< 5 s), `seq 1 10` is enough.
- For long-running commands, increase the loop bound and `block_until_ms`.
- Mask passwords when echoing commands to the user.
