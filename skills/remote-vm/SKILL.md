---
name: remote-vm
description: >-
  Route remote host and VM work to the matching subskill: SSH access and
  command execution, one-time VM bootstrap, and Linux bridge setup on a
  host. Use when the user asks to connect to a VM or host, run remote
  commands, deploy to a VM, check VM status, prepare or bootstrap a new
  VM, create a Linux bridge, attach a NIC to a bridge, or inspect a
  bridge and the device it is built on. Also use when the user mentions
  SSH, remote testing, virtual machines, or a host in the remote-vm
  inventory.
---

# Remote VM

Single entry point for hosts and VMs in the remote-vm inventory
([vms.json](vms.json)). Determine what the user needs, then read **only**
the matching subskill:

- **Connect and run commands** (SSH, tmux session `cursor`, run a command,
  copy a file, check status) →
  Read [remote-vm-access/SKILL.md](remote-vm-access/SKILL.md)
- **Bootstrap a new VM** (virtiofs, tmux, X11, SSH keys, sudo, swap) →
  Read [remote-vm-config/SKILL.md](remote-vm-config/SKILL.md)
- **Linux bridge on a host** (create a bridge, attach a NIC, inspect the
  bridge and the device it is built on) →
  Read [remote-host-config/SKILL.md](remote-host-config/SKILL.md)

Connection and command execution always go through remote-vm-access.
remote-vm-config and remote-host-config say so in their prerequisites.
