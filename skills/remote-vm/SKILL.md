---
name: remote-vm
description: >-
  Connect and run commands on remote virtual machines via SSH. Use when the
  user asks to test on a VM, run commands remotely, deploy to a VM, check
  VM status, or mentions SSH, remote testing, or virtual machines.
---

# Remote VM Testing

**Mandatory:** All commands on a VM MUST run inside a tmux session named `cursor`
on the VM (see user rule `tmux-shell-execution`). Never run remote commands
directly via bare `ssh ... "command"`. The user watches with
`tmux attach -t cursor` on the VM.

## VM Inventory

VM connection details are stored in [vms.json](vms.json). Read that file
to discover available machines before connecting.

Each entry has: `name`, `ip`, `user`, `password`, and an optional
`description`.

## Connecting

Use `sshpass` for password-based authentication. Wrap every remote command in
the tmux-on-VM pattern (host Shell tool runs this block):

```bash
rm -f /tmp/.cursor-vm-out
sshpass -p '<password>' ssh -o StrictHostKeyChecking=no <user>@<ip> bash -s <<'REMOTE_SCRIPT' 2>&1 | tee /tmp/.cursor-vm-out
tmux has-session -t cursor 2>/dev/null || tmux new-session -d -s cursor
rm -f /tmp/.cursor-out
tmux send-keys -t cursor '<REMOTE_COMMAND> 2>&1 | tee /tmp/.cursor-out; echo __CURSOR_DONE__ >> /tmp/.cursor-out' Enter
for i in $(seq 1 300); do grep -q __CURSOR_DONE__ /tmp/.cursor-out 2>/dev/null && break; sleep 1; done
cat /tmp/.cursor-out
REMOTE_SCRIPT
cat /tmp/.cursor-vm-out
```

- Replace `<REMOTE_COMMAND>` with the actual command (escape inner single quotes).
- For fast checks use `seq 1 10`; for OpenStack/devstack use `seq 1 300` and
  matching `block_until_ms`.
- Mask passwords when showing commands to the user.

File transfers (scp) are the only exception — they do not use tmux:

```bash
sshpass -p '<password>' scp -o StrictHostKeyChecking=no <local_path> <user>@<ip>:<remote_path>
sshpass -p '<password>' scp -o StrictHostKeyChecking=no <user>@<ip>:<remote_path> <local_path>
```

## Workspace

Each VM will have a working directory in `/opt/stack/`. All project repositories will be stored
in this directory. This is a shared file with the host server, mapped to `/opt/stack`. Any
change done in the host server files will be seen in the VM and viceversa.


## Workflow

1. Read `vms.json` to find the target VM (by name or let the user choose).
2. Verify connectivity with the tmux-on-VM pattern (`echo ok` as `<REMOTE_COMMAND>`).
3. Run all further commands on the VM through the same tmux-on-VM pattern.
4. Tell the user they can `ssh <user>@<ip>` then `tmux attach -t cursor` to watch live.
5. Report output back to the user.

If the user does not specify which VM, list the available names and ask.

## Security Notes

- `vms.json` should have restricted permissions (`chmod 600`).
- Never log or display passwords in command output; mask them when
  echoing commands to the user.
- Prefer SSH keys when possible. If a VM entry has no `password` field,
  fall back to key-based auth (`ssh <user>@<ip>`).
