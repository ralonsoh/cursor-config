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
`description` and `jump_host`.

Example `vms.json`:

```json
[
  {
    "name": "u24ovn1",
    "ip": "192.168.10.180",
    "user": "stack",
    "password": "stack",
    "description": "Ubuntu 24, OVN backend"
  },
  {
    "name": "remote-lab",
    "ip": "10.0.0.50",
    "user": "developer",
    "description": "Remote lab behind bastion",
    "jump_host": "bastion.example.com"
  }
]
```

The `jump_host` field is optional. When present, SSH connections route through
that host via `-J` (ProxyJump). The jump host value can be:
- A plain hostname or IP (uses your default SSH user/key): `"bastion.example.com"`
- A `user@host` string: `"admin@bastion.example.com"`
- A `user@host:port` string: `"admin@bastion.example.com:2222"`
- An SSH config Host alias: `"my-bastion"` (resolved via `~/.ssh/config`)

## SSH Config Lookup

Before connecting, **always read `~/.ssh/config`** to resolve connection
parameters. SSH config entries take precedence over `vms.json` fields when
both exist, except for `password` (SSH config does not store passwords).

Lookup procedure:

1. Read `~/.ssh/config` (typically at `/home/<user>/.ssh/config` or
   `/root/.ssh/config`).
2. Find a `Host` block matching the VM's `name` or `ip`.
3. Extract relevant directives: `HostName`, `User`, `Port`, `IdentityFile`,
   `ProxyJump`, `ProxyCommand`.
4. Merge with `vms.json`: SSH config values override `vms.json` for `ip`
   (from `HostName`), `user` (from `User`), and add jump host info (from
   `ProxyJump` or `ProxyCommand`). The `password` field only comes from
   `vms.json`.

If a matching SSH config Host is found with an `IdentityFile`, prefer
key-based auth even if `vms.json` has a `password`.

Example `~/.ssh/config` entry:

```
Host u24ovn1
    HostName 192.168.10.180
    User stack
    IdentityFile ~/.ssh/id_rsa_lab
    ProxyJump bastion

Host bastion
    HostName bastion.example.com
    User admin
    Port 2222
    IdentityFile ~/.ssh/id_rsa_bastion
```

## Connecting

### Direct connection (no jump host)

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

### Connection via jump host

When `jump_host` is set (from `vms.json` or SSH config `ProxyJump`), add
`-J <jump_host>` to the SSH command:

```bash
rm -f /tmp/.cursor-vm-out
sshpass -p '<password>' ssh -o StrictHostKeyChecking=no -J <jump_host> <user>@<ip> bash -s <<'REMOTE_SCRIPT' 2>&1 | tee /tmp/.cursor-vm-out
tmux has-session -t cursor 2>/dev/null || tmux new-session -d -s cursor
rm -f /tmp/.cursor-out
tmux send-keys -t cursor '<REMOTE_COMMAND> 2>&1 | tee /tmp/.cursor-out; echo __CURSOR_DONE__ >> /tmp/.cursor-out' Enter
for i in $(seq 1 300); do grep -q __CURSOR_DONE__ /tmp/.cursor-out 2>/dev/null && break; sleep 1; done
cat /tmp/.cursor-out
REMOTE_SCRIPT
cat /tmp/.cursor-vm-out
```

If SSH config defines a `ProxyCommand` instead of `ProxyJump`, use
`-o ProxyCommand='<value>'` in place of `-J`.

### Key-based auth (no password, or IdentityFile found in SSH config)

Drop `sshpass` and optionally specify the key:

```bash
rm -f /tmp/.cursor-vm-out
ssh -o StrictHostKeyChecking=no -i <identity_file> -J <jump_host> <user>@<ip> bash -s <<'REMOTE_SCRIPT' 2>&1 | tee /tmp/.cursor-vm-out
tmux has-session -t cursor 2>/dev/null || tmux new-session -d -s cursor
rm -f /tmp/.cursor-out
tmux send-keys -t cursor '<REMOTE_COMMAND> 2>&1 | tee /tmp/.cursor-out; echo __CURSOR_DONE__ >> /tmp/.cursor-out' Enter
for i in $(seq 1 300); do grep -q __CURSOR_DONE__ /tmp/.cursor-out 2>/dev/null && break; sleep 1; done
cat /tmp/.cursor-out
REMOTE_SCRIPT
cat /tmp/.cursor-vm-out
```

Omit `-i <identity_file>` if no explicit key is configured (SSH will use its
default keys). Omit `-J <jump_host>` when there is no jump host.

### General notes

- Replace `<REMOTE_COMMAND>` with the actual command (escape inner single quotes).
- For fast checks use `seq 1 10`; for OpenStack/devstack use `seq 1 300` and
  matching `block_until_ms`.
- Mask passwords when showing commands to the user.

### File transfers

File transfers (scp) are the only exception — they do not use tmux.

Direct:

```bash
sshpass -p '<password>' scp -o StrictHostKeyChecking=no <local_path> <user>@<ip>:<remote_path>
```

Via jump host:

```bash
sshpass -p '<password>' scp -o StrictHostKeyChecking=no -J <jump_host> <local_path> <user>@<ip>:<remote_path>
```

Key-based with jump host:

```bash
scp -o StrictHostKeyChecking=no -i <identity_file> -J <jump_host> <local_path> <user>@<ip>:<remote_path>
```

## Workspace

Each VM will have a working directory in `/opt/stack/`. All project repositories will be stored
in this directory. This is a shared file with the host server, mapped to `/opt/stack`. Any
change done in the host server files will be seen in the VM and viceversa.


## Workflow

1. Read `~/.ssh/config` to collect SSH connection parameters.
2. Read `vms.json` to find the target VM (by name or let the user choose).
3. Merge connection details: SSH config values override `vms.json` for host,
   user, port, jump host, and identity file. Password only comes from `vms.json`.
4. Verify connectivity with the tmux-on-VM pattern (`echo ok` as `<REMOTE_COMMAND>`).
5. Run all further commands on the VM through the same tmux-on-VM pattern.
6. Tell the user they can `ssh <user>@<ip>` (or `ssh <Host-alias>`) then
   `tmux attach -t cursor` to watch live.
7. Report output back to the user.

If the user does not specify which VM, list the available names and ask.

## Security Notes

- `vms.json` should have restricted permissions (`chmod 600`).
- Never log or display passwords in command output; mask them when
  echoing commands to the user.
- Prefer SSH keys when possible. If a VM entry has no `password` field,
  fall back to key-based auth (`ssh <user>@<ip>`).
- When using jump hosts, ensure the jump host key is trusted or use
  `-o StrictHostKeyChecking=no` for both hops.
