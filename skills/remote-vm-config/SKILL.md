---
name: remote-vm-config
description: >-
  Set up a freshly created remote VM for development work: virtiofs shared
  directory access with host UID matching, X11 tools, SSH key-based login for
  root and a non-root user, sshd X11 forwarding and password authentication,
  passwordless sudo, and swap disabling. Use when the user asks to prepare,
  configure, or bootstrap a new VM from the remote-vm inventory.
---

# Remote VM Configuration

One-time setup of a new VM from the [remote-vm](../remote-vm/SKILL.md)
inventory. Run all commands via the remote-vm tmux-on-VM pattern.

The non-root user `stack` is a convention, not a requirement. **Confirm with
the user, or check what non-root users exist in the VM, before assuming
it**:

```bash
getent passwd | awk -F: '$3 >= 1000 && $3 < 65534 {print $1, $3}'
```

Replace `stack` with the actual user in all steps below.

Checklist:

```
- [ ] 1. Shared directory (virtiofs) mounted and accessible
- [ ] 2. X11 tools installed
- [ ] 3. SSH public key login for stack and root
- [ ] 4. sshd: X11 forwarding + password authentication
- [ ] 5. Passwordless sudo for stack
- [ ] 6. Home directory traversable (755)
- [ ] 7. Swap disabled
```

## 1. Shared directory (virtiofs)

The host exports a directory via virtiofs (host user runs unprivileged
`virtiofsd`). The default shared directory is `/opt/stack`, and the default
non-root user is `stack` — both are conventions. **Confirm with the user, or
discover the actual tag and existing VM users, before assuming either.**
The virtiofs tag and mount point can be found with:

```bash
sudo dmesg | grep -i virtiofs    # guest: "discovered new tag: ..."
```

Two things must be fixed in the guest (examples below use `/opt/stack`;
substitute the actual directory):

**Mount.** The kernel discovers the device but nothing mounts it by default:

```bash
sudo mount -t virtiofs <TAG> /opt/stack
grep -q virtiofs /etc/fstab || \
    echo '<TAG> /opt/stack virtiofs defaults 0 0' | sudo tee -a /etc/fstab
```

**UID match.** virtiofs passes host ownership through raw. The guest user
must have the same UID/GID as the host user owning `/opt/stack`, or all
shared files are inaccessible. **Never hardcode a UID** — discover it first
on the host:

```bash
stat -c '%u %g' /opt/stack   # or: id -u; id -g
```

Then compare with the guest (`id stack` and `ls -lan /opt/stack/`). If they
differ, renumber the guest user (must run as root, no stack processes
running), replacing `<HOST_UID>`/`<HOST_GID>` with the discovered values:

```bash
usermod -u <HOST_UID> stack
groupmod -g <HOST_GID> stack
chown -R <HOST_UID>:<HOST_GID> /home/stack
```

Kill `stack` processes (including `tmux kill-server`) before `usermod` —
it refuses while the user owns running processes.

Verify: `head /opt/stack/neutron/setup.cfg` works and
`echo test > /opt/stack/.write-test && rm /opt/stack/.write-test` succeeds.

## 2. X11 tools

```bash
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
    x11-utils x11-apps libxi6 libxrender1 libxtst6
```

`libxi6/libxrender1/libxtst6` are required by GUI apps (e.g. PyCharm's JBR:
`libawt_xawt.so` fails with `libXi.so.6: cannot open shared object file`
without them). Check any failing app with
`ldd <binary> | grep "not found"`.

## 3. SSH key-based login

**Always ask the user for the public key to install** — never guess or reuse
one without confirmation.

Install into `authorized_keys` (NOT `known_hosts` — that file stores *host*
keys on clients) for both users, with correct permissions:

```bash
KEY='<user-provided public key>'
for u in stack root; do
  d=$(getent passwd $u | cut -d: -f6)/.ssh
  mkdir -p $d
  grep -qF "$KEY" $d/authorized_keys 2>/dev/null || echo "$KEY" >> $d/authorized_keys
  chown -R $u:$u $d; chmod 700 $d; chmod 600 $d/authorized_keys
done
```

Verify both logins from the host:

```bash
ssh -o PasswordAuthentication=no stack@<ip> 'whoami'
ssh -o PasswordAuthentication=no root@<ip> 'whoami'
```

## 4. sshd configuration

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

## 5. Passwordless sudo

```bash
printf 'stack ALL=(ALL) NOPASSWD:ALL\n' | \
    sudo tee /etc/sudoers.d/stack
sudo chmod 440 /etc/sudoers.d/stack
sudo visudo -c   # must report "parsed OK"
```

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
