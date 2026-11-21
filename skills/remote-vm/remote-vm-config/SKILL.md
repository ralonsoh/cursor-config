---
name: remote-vm-config
description: >-
  Set up a freshly created remote VM for development work: virtiofs or NFS
  shared directory access with host UID matching, passwordless sudo
  bootstrap, tmux with mouse support, X11 tools, SSH key-based login for
  root and a non-root user, sshd X11 forwarding and password
  authentication, home directory permissions, and swap disabling. Use when
  the user asks to prepare, configure, or bootstrap a new VM from the
  remote-vm inventory.
---

# Remote VM Configuration

One-time setup of a new VM from the [remote-vm](../SKILL.md) inventory.
Run all commands via the [remote-vm-access](../remote-vm-access/SKILL.md)
tmux-on-VM pattern.

The non-root user `stack` is a convention, not a requirement. **Confirm with
the user, or check what non-root users exist in the VM, before assuming
it**:

```bash
getent passwd | awk -F: '$3 >= 1000 && $3 < 65534 {print $1, $3}'
```

Replace `stack` with the actual user in all steps below.

Checklist:

```
- [ ] 0. Passwordless sudo bootstrapped (all later steps need it)
- [ ] 1. Shared directory mounted and accessible (ask user: virtiofs or
      NFS; for NFS also the server IP and exported directory)
- [ ] 2. tmux installed with mouse support
- [ ] 3. X11 tools installed
- [ ] 4. SSH public key login for stack and root
- [ ] 5. sshd: X11 forwarding + password authentication
- [ ] 6. Home directory traversable (755)
- [ ] 7. Swap disabled
```

## 0. Bootstrap passwordless sudo (do this FIRST)

Every later step runs `sudo` inside the tmux session, where no password
prompt can be answered over SSH. On a fresh VM the non-root user needs
a password for sudo, so steps 1-7 silently hang or fail ("sudo: a
terminal is required") until this is done. Bootstrap it directly over
SSH, not via tmux:

```bash
sshpass -p '<password>' ssh <user>@<ip> \
    "echo '<password>' | sudo -S bash -c 'printf \"<user> ALL=(ALL) NOPASSWD:ALL\n\" > /etc/sudoers.d/<user>; chmod 440 /etc/sudoers.d/<user>; visudo -c'"
```

Verify before continuing: `ssh <user>@<ip> 'sudo -n true && echo OK'`.

## 1. Shared directory (virtiofs or NFS)

`/opt/stack` is shared between the VM and the machine that hosts the
repositories. There are two **mutually exclusive** mechanisms, and the
steps differ. Before doing anything in this section, **ask the user:**

1. Which mechanism to use: **virtiofs** (the VM's own hypervisor exports
   the directory) or **NFS** (another machine exports it over the
   network). Never assume — check, but confirm the answer with the user.
2. For NFS only: the **server IP** and the **exported directory** on that
   server (e.g. `192.168.1.99` exporting `/opt/stack`).

Then follow **only** the matching subsection below. The default shared
directory mount point is `/opt/stack` and the default non-root user is
`stack` — both are conventions; confirm with the user, or discover the
actual tag and existing VM users, before assuming either.

Both mechanisms pass file ownership through raw (sec=sys), so in either
case the guest user must have the same UID/GID as the user owning the
directory on the exporting machine, or all shared files are
inaccessible.

### 1a. virtiofs (hypervisor export)

The VM's hypervisor runs an unprivileged `virtiofsd` exporting the
directory. The virtiofs tag and mount point can be found with:

```bash
sudo dmesg | grep -i virtiofs    # guest: "discovered new tag: ..."
```

**Mount.** The kernel discovers the device but nothing mounts it by
default:

```bash
sudo mount -t virtiofs <TAG> /opt/stack
grep -q virtiofs /etc/fstab || \
    echo '<TAG> /opt/stack virtiofs defaults 0 0' | sudo tee -a /etc/fstab
```

**UID match.** **Never hardcode a UID** — discover it first on the
hypervisor (the machine running `virtiofsd`):

```bash
stat -c '%u %g' /opt/stack   # or: id -u; id -g
```

Then compare with the guest (`id stack` and `ls -lan /opt/stack/`). If
they differ, renumber the guest user (must run as root, no stack
processes running), replacing `<HOST_UID>`/`<HOST_GID>` with the
discovered values:

```bash
usermod -u <HOST_UID> stack
groupmod -g <HOST_GID> stack
chown -R <HOST_UID>:<HOST_GID> /home/stack
```

Kill `stack` processes (including `tmux kill-server`) before `usermod` —
it refuses while the user owns running processes.

**Run the UID change detached as root** — `pkill -u stack` kills the SSH
session running the script, aborting it before `usermod` executes. Wrap
it in `setsid nohup ... &` over a sudo one-liner, then poll from a fresh
connection:

```bash
sshpass -p '<password>' ssh <user>@<ip> \
    "echo '<password>' | sudo -S bash -c 'setsid nohup bash -c \"pkill -u <user>; sleep 2; usermod -u <HOST_UID> <user>; groupmod -g <HOST_GID> <user>; chown -R <HOST_UID>:<HOST_GID> /home/<user>; echo FINISHED > /tmp/uidchange.done\" > /tmp/uidchange.log 2>&1 &'"
sleep 15
sshpass -p '<password>' ssh <user>@<ip> 'cat /tmp/uidchange.done; id <user>'
```

**After the change, files the old UID created are inaccessible** (e.g.
`/tmp/.cursor-out` from earlier tmux steps): `sudo rm -f` them and
restart the tmux server before continuing.

Verify: `head /opt/stack/neutron/setup.cfg` works and
`echo test > /opt/stack/.write-test && rm /opt/stack/.write-test`
succeeds.

### 1b. NFS (export from another machine)

A machine other than the VM's hypervisor (typically a baremetal host on
the LAN) exports the directory over NFS. Use the server IP and exported
directory the user provided. The NFS server must export to the VM's
subnet with `sec=sys` (raw UIDs) and `no_root_squash`.

**Server side — ask the user first.** By default the agent does not
touch the NFS server: it is a different machine, possibly outside the
remote-vm inventory, and the agent may not even have access to it. Ask
the user to set up (or confirm) the export themselves, and only run the
steps below on the server if the user explicitly asks. Check what is
already in place first with `sudo exportfs -v`:

```bash
echo '<export_dir>  <vm_subnet>(rw,sync,no_subtree_check,no_root_squash)' | \
    sudo tee -a /etc/exports
sudo exportfs -rav
sudo systemctl enable --now nfs-server
```

**Guest side:**

```bash
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y nfs-common
sudo mkdir -p /opt/stack
grep -q '<server>:<export_dir> /opt/stack' /etc/fstab || \
    echo '<server>:<export_dir> /opt/stack nfs defaults,_netdev 0 0' | \
    sudo tee -a /etc/fstab
sudo mount -a
mount | grep /opt/stack    # must show type nfs4, rw
```

**UID match.** **Never hardcode a UID** — discover the raw owner first.
Prefer asking the user or running, on the NFS server:

```bash
stat -c '%u %g' /opt/stack   # on the NFS server
```

Without access to the server, mount the share first and read the raw
ownership from the guest (root can read it even when the user cannot):

```bash
sudo ls -lan /opt/stack/     # guest, after mounting
```

Then compare with the guest (`id stack` and `ls -lan /opt/stack/`). If
they differ, renumber the guest user (must run as root, no stack
processes running), replacing `<SERVER_UID>`/`<SERVER_GID>` with the
discovered values:

```bash
usermod -u <SERVER_UID> stack
groupmod -g <SERVER_GID> stack
chown -R <SERVER_UID>:<SERVER_GID> /home/stack
```

Kill `stack` processes (including `tmux kill-server`) before `usermod` —
it refuses while the user owns running processes.

**Run the UID change detached as root** — `pkill -u stack` kills the SSH
session running the script, aborting it before `usermod` executes. Wrap
it in `setsid nohup ... &` over a sudo one-liner, then poll from a fresh
connection:

```bash
sshpass -p '<password>' ssh <user>@<ip> \
    "echo '<password>' | sudo -S bash -c 'setsid nohup bash -c \"pkill -u <user>; sleep 2; usermod -u <SERVER_UID> <user>; groupmod -g <SERVER_GID> <user>; chown -R <SERVER_UID>:<SERVER_GID> /home/<user>; echo FINISHED > /tmp/uidchange.done\" > /tmp/uidchange.log 2>&1 &'"
sleep 15
sshpass -p '<password>' ssh <user>@<ip> 'cat /tmp/uidchange.done; id <user>'
```

**After the change, files the old UID created are inaccessible** (e.g.
`/tmp/.cursor-out` from earlier tmux steps): `sudo rm -f` them and
restart the tmux server before continuing.

**Order matters:** when the server-side UID is already known (user told
it, or the agent has access to the server), renumber the guest user
before mounting. When discovering the raw owner from a mounted share,
the UIDs will not match yet — that is expected; the share is
temporarily accessible only to root until the renumber is done.

Verify: `head /opt/stack/neutron/setup.cfg` works and
`echo test > /opt/stack/.write-test && rm /opt/stack/.write-test`
succeeds.

## 2. tmux with mouse support

The remote-vm-access skill drives the VM through a tmux session, and the user
interactively attaches to it. Enable mouse support so that selecting
with the mouse and scrolling work as expected (see the notes on
copy/paste below).

```bash
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y tmux
sudo tee /etc/tmux.conf > /dev/null <<'EOF'
set -g mouse on
set -g set-clipboard off
EOF
```

The heredoc form is for interactive use. When driving this through the
tmux-on-VM pattern, `tmux send-keys` cannot send multi-line commands —
each line would be executed as a separate shell line. Flatten it to a
single line first:

```bash
printf 'set -g mouse on\nset -g set-clipboard off\n' | \
    sudo tee /etc/tmux.conf > /dev/null
```

**Why `/etc/tmux.conf` (system-wide) instead of `~/.tmux.conf`:** the
setup is per-VM, not per-user. The `remote-vm-access` skill runs tmux as the
`stack` user, but interactive sessions often run under `root` too
(separate tmux servers); a system-wide config covers both without
needing per-user copies.

**Copy/paste behavior with `mouse on` and `set-clipboard off`:** mouse
scrolling and pane selection still work, but releasing a mouse drag no
longer copies anything — `set-clipboard off` disables the OSC 52
clipboard integration entirely, so selections stay local to tmux. To
copy text, hold `Shift` while dragging to bypass tmux mouse handling and
get a plain terminal selection, then copy it with `Ctrl+Shift+C` (or the
terminal's context menu). Without `Shift`, the terminal never sees the
selection, so `Ctrl+Shift+C` after a tmux drag does nothing useful — the
key falls through to the application as `Ctrl+C` (it can kill htop and
friends).

Set `set-clipboard external` instead of `off` to restore copy-on-release
via OSC 52 (works over SSH, no X11/agent needed) if that behavior is
preferred later.

## 3. X11 tools

```bash
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
    x11-utils x11-apps libxi6 libxrender1 libxtst6
```

`libxi6/libxrender1/libxtst6` are required by GUI apps (e.g. PyCharm's JBR:
`libawt_xawt.so` fails with `libXi.so.6: cannot open shared object file`
without them). Check any failing app with
`ldd <binary> | grep "not found"`.

## 4. SSH key-based login

**Always ask the user for the public key to install** — never guess or reuse
one without confirmation.

Install into `authorized_keys` (NOT `known_hosts` — that file stores *host*
keys on clients) for both users, with correct permissions.

The key must reach the VM without breaking the tmux-on-VM quoting: scp it
over first (file transfers are the scp exception in remote-vm-access):

```bash
scp <key>.pub <user>@<ip>:/tmp/key.pub
```

Install for the non-root user (unprivileged is fine):

```bash
d=$(getent passwd <user> | cut -d: -f6)/.ssh
mkdir -p $d
grep -qF -f /tmp/key.pub $d/authorized_keys 2>/dev/null || \
    cat /tmp/key.pub >> $d/authorized_keys
chown -R <user>:<user> $d; chmod 700 $d; chmod 600 $d/authorized_keys
```

Install for root **with sudo** — a plain loop over `stack root` runs
unprivileged and fails on `/root/.ssh` with permission denied:

```bash
sudo mkdir -p /root/.ssh
sudo grep -qF -f /tmp/key.pub /root/.ssh/authorized_keys 2>/dev/null || \
    sudo tee -a /root/.ssh/authorized_keys < /tmp/key.pub > /dev/null
sudo chown -R root:root /root/.ssh; sudo chmod 700 /root/.ssh
sudo chmod 600 /root/.ssh/authorized_keys
rm -f /tmp/key.pub
```

Verify both logins from the host:

```bash
ssh -o PasswordAuthentication=no stack@<ip> 'whoami'
ssh -o PasswordAuthentication=no root@<ip> 'whoami'
```

## 5. sshd configuration

```bash
printf 'X11Forwarding yes\nPasswordAuthentication yes\n' | \
    sudo tee /etc/ssh/sshd_config.d/60-vm-config.conf
sudo sshd -t && sudo systemctl restart ssh
sudo sshd -T | grep -Ei 'x11forwarding|passwordauthentication'
```

On Ubuntu the stock config already has `X11Forwarding yes`; a drop-in in
`sshd_config.d/` wins over the commented defaults regardless. If root login
with password is requested, also set `PermitRootLogin yes` in the drop-in,
set the root password (`echo 'root:<pw>' | sudo chpasswd` — root is locked
by default on Ubuntu), and ask the user what password to use.

## 6. Home directory traversable (755)

The non-root user's home must be world-traversable, especially when devstack
puts the global venv under it (`DATA_DIR=/home/<user>/...`):

```bash
stat -c '%a' /home/stack    # 750 is too restrictive
chmod 755 /home/stack
```

**Why:** services that run as other users need to traverse the home to
reach the venv. Concretely, devstack's Horizon runs under Apache as
`www-data` with mod_wsgi pointed at the global venv under the home as its
Python home. With mode 750, `www-data` cannot stat the venv, mod_wsgi
fails to initialize Python (`Failed to import encodings module`) and the
workers **segfault in a loop**. Apache fronts port 80 and proxies every
OpenStack API (`/identity`, `/placement`, ...), so the whole deployment
wedges — observed as stack.sh hanging forever in `init_placement`
waiting on a keystone call that never returns. `chmod 755` on the home
fixes it.

Verify:

```bash
sudo -u www-data ls /home/stack/data/venv/bin/python
```

## 7. Disable swap

Development workloads (e.g. DevStack, OVN) expect no swap. Disable it now
and comment out the fstab entry so it does not come back on reboot:

```bash
sudo swapoff -a
sudo sed -i.bak -e "/\sswap\s/s/^/# disabled /" /etc/fstab
free -h | grep -i swap   # must show 0B total
swapon --show            # must print nothing
```

The swap file (commonly `/swap.img` or `/swapfile`) can be removed to free
disk space once confirmed unused — ask the user first.

## Notes

- Do these steps early in a VM's life; the UID change in step 1 is
  disruptive (kills user sessions) and best done before any work starts.
- Remind the user to connect with `ssh -X` (or `-Y`) for X11 forwarding.
- Masking `systemd-networkd-wait-online.service` is NOT part of this setup;
  if boot hangs 2 minutes, see the netplan `optional: true` fix for unused
  interfaces.
