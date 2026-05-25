---
name: remote-vm
description: >-
  Connect and run commands on remote virtual machines via SSH. Use when the
  user asks to test on a VM, run commands remotely, deploy to a VM, check
  VM status, or mentions SSH, remote testing, or virtual machines.
---

# Remote VM Testing

## VM Inventory

VM connection details are stored in [vms.json](vms.json). Read that file
to discover available machines before connecting.

Each entry has: `name`, `ip`, `user`, `password`, and an optional
`description`.

## Connecting

Use `sshpass` for password-based authentication:

```bash
sshpass -p '<password>' ssh -o StrictHostKeyChecking=no <user>@<ip> "<command>"
```

For multi-command sessions or file transfers:

```bash
# Run a script remotely
sshpass -p '<password>' ssh -o StrictHostKeyChecking=no <user>@<ip> 'bash -s' < local_script.sh

# Copy files to/from the VM
sshpass -p '<password>' scp -o StrictHostKeyChecking=no <local_path> <user>@<ip>:<remote_path>
sshpass -p '<password>' scp -o StrictHostKeyChecking=no <user>@<ip>:<remote_path> <local_path>
```

## Workspace

Each VM will have a working directory in `/opt/stack/`. All project repositories will be stored
in this directory. This is a shared file with the host server, mapped to `/opt/stack`. Any
change done in the host server files will be seen in the VM and viceversa.


## Workflow

1. Read `vms.json` to find the target VM (by name or let the user choose).
2. Verify connectivity: `sshpass -p '<pw>' ssh ... "echo ok"`.
3. Run the requested command(s) on the VM.
4. Report output back to the user.

If the user does not specify which VM, list the available names and ask.

## Security Notes

- `vms.json` should have restricted permissions (`chmod 600`).
- Never log or display passwords in command output; mask them when
  echoing commands to the user.
- Prefer SSH keys when possible. If a VM entry has no `password` field,
  fall back to key-based auth (`ssh <user>@<ip>`).
