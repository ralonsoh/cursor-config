---
name: rhoso-code
description: >-
  Mount local code into a RHOSO 18.0 pod via NFS and extraMounts to test
  live code changes. Use when the user asks to test code in RHOSO, mount
  code into an OpenStack pod, create an NFS share for a service, or debug
  live OpenStack code on OpenShift.
---

# RHOSO Code Testing

Mount a local code directory into an OpenStack service pod running in a
RHOSO 18.0 environment so that code changes can be tested live.

Based on the [upstream dev-docs guide](https://github.com/openstack-k8s-operators/dev-docs/blob/main/testing_openstack_code_changes_with_operators.md).

## Prerequisites

- Follow the `rhoso-access` subskill ([rhoso-access/SKILL.md](../rhoso-access/SKILL.md),
  sibling directory of this skill) to access the RHOSO controller and
  log into OpenShift (`oc login`).
- The code directory to mount must exist on the controller (or on a
  host reachable via NFS from all OCP nodes).

## Variables

Collect these from the user before proceeding:

| Variable | Example | Description |
|----------|---------|-------------|
| `SERVICE` | `neutron` | OpenStack service name |
| `CODE_PATH` | `/home/zuul/neutron/neutron` | Path to the code directory on the NFS server |
| `NFS_SERVER` | `192.168.122.1` | IP of the NFS server (reachable from all OCP nodes) |
| `NFS_SUBNET` | `192.168.122.0/24` | Subnet allowed to access the NFS share |
| `MOUNT_PATH` | `/usr/lib/python3.9/site-packages/neutron` | Target path inside the pod |
| `OSCP_NAME` | (from `oc get openstackcontrolplane -n openstack`) | Name of the OSCP CR |

## Step 1: Create Local NFS Storage

On the **NFS server** (typically the controller), export the code directory:

```bash
echo "${CODE_PATH} ${NFS_SUBNET}(rw,sync,no_root_squash)" >> /etc/exports
exportfs -r
```

## Step 2: Enable NFS and Firewall Services

```bash
systemctl start nfs-server
systemctl enable nfs-server
systemctl start firewalld
systemctl enable firewalld
```

If `firewalld` is running and blocks NFS traffic, add an nftables rule
to allow it:

```bash
nft add rule inet firewalld filter_IN_libvirt_pre accept
```

Verify the export is visible:

```bash
showmount -e ${NFS_SERVER}
```

## Step 3: Create PV and PVC

On the **controller** (logged into OCP), create the PersistentVolume and
PersistentVolumeClaim:

```bash
cat <<EOF | oc apply -f -
apiVersion: v1
kind: PersistentVolume
metadata:
  name: ${SERVICE}-code
spec:
  capacity:
    storage: 1Gi
  volumeMode: Filesystem
  accessModes:
    - ReadOnlyMany
  persistentVolumeReclaimPolicy: Retain
  storageClassName: ${SERVICE}-code
  mountOptions:
    - nfsvers=4.1
  nfs:
    path: ${CODE_PATH}
    server: ${NFS_SERVER}
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: ${SERVICE}-code-dev
  namespace: openstack
spec:
  storageClassName: ${SERVICE}-code
  accessModes:
    - ReadOnlyMany
  resources:
    requests:
      storage: 1Gi
EOF
```

Verify PV and PVC are bound:

```bash
oc get pv ${SERVICE}-code
oc get pvc ${SERVICE}-code-dev -n openstack
```

## Step 4: Add ExtraMount to the OSCP CR

Patch the OpenStackControlPlane to mount the code into the service pod:

```bash
oc patch openstackcontrolplane ${OSCP_NAME} -n openstack --type merge -p '
spec:
  '${SERVICE}':
    template:
      extraMounts:
        - name: '${SERVICE}'-code
          extraVol:
            - extraVolType: '${SERVICE}'-code
              mounts:
                - mountPath: '${MOUNT_PATH}'
                  name: '${SERVICE}'-code
              volumes:
                - name: '${SERVICE}'-code
                  persistentVolumeClaim:
                    claimName: '${SERVICE}'-code-dev
                    readOnly: true
'
```

## Step 5: Verify the Pod

Wait for the pod to be recreated and check the mount:

```bash
oc get pods -n openstack -l service=${SERVICE} -w
```

Once the pod is running, confirm the volume is mounted:

```bash
oc describe $(oc get pods -n openstack -l service=${SERVICE} -o name | head -1) -n openstack | grep -A5 "Mounts:"
```

Check that the code files are visible inside the pod:

```bash
oc exec $(oc get pods -n openstack -l service=${SERVICE} -o name | head -1) -n openstack -- ls ${MOUNT_PATH}
```

## Workflow Summary

```
Task Progress:
- [ ] Access RHOSO controller and oc login (rhoso-access subskill)
- [ ] Collect variables (SERVICE, CODE_PATH, NFS_SERVER, etc.)
- [ ] Export NFS share and reload exports
- [ ] Start nfs-server and firewalld; add nft rule if needed
- [ ] Create PV and PVC; verify they are bound
- [ ] Patch OSCP CR with extraMount
- [ ] Verify pod recreated with the code volume mounted
```

## Cleanup

To remove the code mount and restore the original pod:

1. Remove the `extraMounts` entry from the OSCP CR (use `oc edit` or
   patch with the original spec).
2. Delete the PVC and PV:

```bash
oc delete pvc ${SERVICE}-code-dev -n openstack
oc delete pv ${SERVICE}-code
```

3. Remove the NFS export from `/etc/exports` and reload:

```bash
exportfs -r
```

## Troubleshooting

- **PVC stuck in Pending**: Check that the PV `storageClassName` matches
  the PVC and that the NFS server is reachable from all OCP nodes.
- **Pod fails to start**: Check events with
  `oc describe pod <pod> -n openstack` — look for mount errors.
- **Permission denied inside pod**: Verify the NFS export has
  `no_root_squash` and the subnet is correct.
- **Code changes not visible**: NFS caches aggressively; try
  `mount -o remount` inside the pod or restart the pod with
  `oc delete pod <pod> -n openstack`.
