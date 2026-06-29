---
name: openstack-neutron-endpoint
description: >-
  Switch the Neutron Keystone endpoint between DevStack (Apache UWSGI) and
  PyCharm remote debugger, then restart dependent services. Use when the user
  asks to switch Neutron to debug mode, PyCharm, devstack mode, or change the
  Neutron endpoint on a VM.
---

# Switch Neutron Endpoint

Switch the Neutron endpoint registered in Keystone between the default DevStack
service and the PyCharm remote debugger, then restart every OpenStack service
that talks to Neutron so they pick up the new URL.

## Prerequisites

Read the [remote-vm skill](../remote-vm/SKILL.md) for SSH/tmux connection
details and VM inventory.

## Endpoint modes

| Mode | URL pattern | Description |
|------|-------------|-------------|
| **devstack** | `http://<VM_IP>/networking` | Default Apache UWSGI proxy |
| **pycharm** | `http://<VM_IP>:8000` | PyCharm remote debug server |

`<VM_IP>` comes from `vms.json` for the target VM.

## Workflow

### 1. Determine target mode

If the user does not specify, ask which mode to switch to using AskQuestion:
- "DevStack (default Apache service)"
- "PyCharm (remote debugger on port 8000)"

### 2. Connect and source admin credentials

Use the remote-vm tmux-on-VM pattern from [vms.json](../remote-vm/vms.json).
All OpenStack CLI commands must be prefixed with:

```
. /opt/stack/devstack/openrc admin demo
```

### 3. Discover the Neutron endpoint ID

```bash
openstack endpoint list --service network -f value -c ID -c URL
```

This returns the endpoint ID and current URL. Do **not** hardcode the endpoint
ID — it changes across re-stacks.

### 4. Update the endpoint

Compute the target URL from the mode and `<VM_IP>`:

| Mode | Target URL |
|------|------------|
| devstack | `http://<VM_IP>/networking` |
| pycharm  | `http://<VM_IP>:8000` |

If the current URL already matches the target, inform the user and skip the
update.

```bash
openstack endpoint set --url <TARGET_URL> <ENDPOINT_ID>
```

Verify with:

```bash
openstack endpoint show <ENDPOINT_ID> -f value -c url
```

### 5. Stop or start the Neutron API service

The Neutron API DevStack service runs behind Apache UWSGI. It must be stopped
when switching to PyCharm (to free the API) and started when switching back.

| Mode | Action |
|------|--------|
| pycharm  | `sudo systemctl stop devstack@neutron-api.service` |
| devstack | `sudo systemctl start devstack@neutron-api.service` |

Verify the expected state after the action:

```bash
systemctl is-active devstack@neutron-api.service
```

- **pycharm** mode: must report `inactive`.
- **devstack** mode: must report `active`.

### 6. Restart dependent services

These Nova services cache the Neutron endpoint and must be restarted:

```bash
sudo systemctl restart devstack@n-api.service
sudo systemctl restart devstack@n-cpu.service
sudo systemctl restart devstack@n-cond-cell1.service
sudo systemctl restart devstack@n-api-meta.service
```

Run the four restarts in a single command joined with `&&`.

After restarting, verify they are active:

```bash
systemctl is-active devstack@n-api.service devstack@n-cpu.service devstack@n-cond-cell1.service devstack@n-api-meta.service
```

All four must report `active`.

### 7. Report

Print a summary:

```
Neutron endpoint switched to <MODE>
  URL: <TARGET_URL>
  Neutron API service: <stopped|started>
  Restarted: n-api, n-cpu, n-cond-cell1, n-api-meta
```
