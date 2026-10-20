---
name: rhoso-debug
description: >-
  Access and debug a RHOSO 18.0 testing environment deployed on baremetal.
  Use when the user asks to connect to a RHOSO environment, debug OpenStack
  on OpenShift, inspect OCP cluster nodes, check OpenStack operators or
  services, or mentions RHOSO, RHOSO 18, baremetal cluster, or OCP OpenStack.
---

# RHOSO 18.0 Debug Environment, Log into OpenShift

Steps to access and debug a Red Hat OpenStack Services on OpenShift (RHOSO)
18.0 testing environment deployed on a baremetal node.

## Prerequisites

- Root SSH access to the baremetal node (use the `remote-vm` skill to
  connect; the baremetal node must be in `vms.json` or `~/.ssh/config`).
- The `zuul` user's SSH key must be shared for controller access.

## Step 1: Discover Cluster Nodes

On the **baremetal node**, read the dnsmasq DHCP host files to discover
cluster member IPs and names:

```bash
ls /etc/cifmw-dnsmasq.d/dhcp-hosts.d/
```

Parse the `ocpbm_*` files to extract node names and IPs:

```bash
cat /etc/cifmw-dnsmasq.d/dhcp-hosts.d/ocpbm_*
```

Each file contains entries mapping MAC addresses to IPs and hostnames.
Build an inventory of nodes from these files (compute-*, master-*,
ceph-*, etc.).

## Step 2: SSH into the Controller

Look up the controller hostname (usually `controller-0`) in `/etc/hosts`
on the baremetal node:

```bash
grep controller /etc/hosts
```

SSH into the controller as the `zuul` user (key-based auth):

```bash
ssh -o StrictHostKeyChecking=no zuul@controller-0
```

## Step 3: Log into OpenShift

On the **controller**, authenticate to the OCP cluster:

```bash
oc login -u kubeadmin -p $(cat /home/zuul/.kube/kubeadmin-password) https://api.ocp.openstack.lab:6443
```

Verify the login:

```bash
oc whoami
```

# Inspect the Environment

## Main Namespaces

| Namespace | Contents |
|-----------|----------|
| `openstack-operators` | OpenStack operators that define the services |
| `openstack` | OpenStack services (running workloads) |

## OSCP Deployment Status

**Get the OpenStackControlPlane (OSCP) resource:**

```bash
oc get openstackcontrolplane -n openstack
```

**Check OSCP readiness conditions:**

```bash
oc get openstackcontrolplane -n openstack -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{range .status.conditions[*]}  {.type}: {.status} ({.reason}) {.message}{"\n"}{end}{end}'
```

**Check individual service deployment status within OSCP:**

```bash
oc get openstackcontrolplane -n openstack -o yaml | grep -A2 'deployedVersion\|ready\|readyCount'
```

**List all OpenStack CRDs and their instances:**

```bash
oc get $(oc api-resources --api-group=core.openstack.org -o name | tr '\n' ',' | sed 's/,$//') -n openstack 2>/dev/null
```

**Check DataPlaneNodeSet status:**

```bash
oc get openstackdataplanenodeset -n openstack
oc get openstackdataplanenodeset -n openstack -o jsonpath='{range .items[*]}{.metadata.name}: ready={.status.conditions[?(@.type=="Ready")].status}{"\n"}{end}'
```

**Check DataPlaneDeployment status:**

```bash
oc get openstackdataplanedeployment -n openstack
```

## Common Debug Commands

**List OpenStack operators:**

```bash
oc get pods -n openstack-operators
```

**List OpenStack service pods:**

```bash
oc get pods -n openstack
```

**Check operator status:**

```bash
oc get csv -n openstack-operators
```

**Inspect a specific pod's logs:**

```bash
oc logs <pod-name> -n openstack
```

**Describe a failing pod:**

```bash
oc describe pod <pod-name> -n openstack
```

**Check OpenStackControlPlane CR:**

```bash
oc get openstackcontrolplane -n openstack -o yaml
```

**Check OpenStack services status:**

```bash
oc get openstackcontrolplane -n openstack -o jsonpath='{.items[*].status.conditions}' | python3 -m json.tool
```

# Edit the OSCP

All changes to OpenStack services are made by patching the
`OpenStackControlPlane` (OSCP) CR in the `openstack` namespace.

## Get the Current OSCP Definition

```bash
oc get openstackcontrolplane -n openstack -o yaml > /tmp/oscp.yaml
```

## Change Service Replicas

Scale a service by patching its `replicas` field. Replace `<service>` with
the service name (e.g. `neutron`, `nova`, `glance`, `cinder`, `keystone`):

```bash
oc patch openstackcontrolplane <oscp-name> -n openstack --type merge -p '
spec:
  <service>:
    template:
      replicas: <count>
'
```

Example — scale Neutron to 3 replicas:

```bash
oc patch openstackcontrolplane <oscp-name> -n openstack --type merge -p '
spec:
  neutron:
    template:
      replicas: 3
'
```

## Add an ExtraMount to a Service

ExtraMounts inject additional volumes into service pods (config files,
scripts, certificates, etc.). They are added under the service's
`template.extraMounts` list.

```bash
oc patch openstackcontrolplane <oscp-name> -n openstack --type merge -p '
spec:
  <service>:
    template:
      extraMounts:
        - name: <mount-name>
          region: <region>
          extraVol:
            - propagation:
                - <service>
              extraVolType: <vol-type>
              volumes:
                - name: <volume-name>
                  configMap:
                    name: <configmap-name>
              mounts:
                - name: <volume-name>
                  mountPath: <path-inside-pod>
                  readOnly: true
'
```

Example — mount a custom config into Neutron pods:

```bash
oc create configmap neutron-custom-config -n openstack --from-file=custom.conf=/tmp/custom.conf

oc patch openstackcontrolplane <oscp-name> -n openstack --type merge -p '
spec:
  neutron:
    template:
      extraMounts:
        - name: neutron-custom
          region: r1
          extraVol:
            - propagation:
                - Neutron
              extraVolType: Undefined
              volumes:
                - name: neutron-custom-config
                  configMap:
                    name: neutron-custom-config
              mounts:
                - name: neutron-custom-config
                  mountPath: /etc/neutron/neutron.conf.d/custom.conf
                  subPath: custom.conf
                  readOnly: true
'
```

## Verify Changes

After patching, wait for the rollout and verify:

```bash
oc get openstackcontrolplane -n openstack -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{range .status.conditions[*]}  {.type}: {.status} ({.reason}){"\n"}{end}{end}'
oc get pods -n openstack | grep <service>
```

# Workflow Summary

```
Task Progress:
- [ ] Connect to baremetal node (via remote-vm skill)
- [ ] Read /etc/cifmw-dnsmasq.d/dhcp-hosts.d/ocpbm_* for node inventory
- [ ] Resolve controller hostname from /etc/hosts
- [ ] SSH to controller as zuul
- [ ] oc login to OCP cluster
- [ ] Inspect namespaces (openstack-operators, openstack)
```

# Troubleshooting

- **oc login fails**: Check that `/home/zuul/.kube/kubeadmin-password` exists
  and the API endpoint is reachable (`curl -k https://api.ocp.openstack.lab:6443`).
- **SSH to controller fails**: Verify the controller IP in `/etc/hosts` and
  that the zuul key is deployed (`ssh-copy-id zuul@controller-0`).
- **Pods in CrashLoopBackOff**: Check logs with `oc logs --previous <pod> -n openstack`
  and describe with `oc describe pod <pod> -n openstack`.
