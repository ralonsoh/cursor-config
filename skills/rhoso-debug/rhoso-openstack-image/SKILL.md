---
name: rhoso-openstack-image
description: >-
  Retrieve the container image of a RHOSO OpenStack pod and change it by
  patching the OpenStackControlPlane CR. Use when the user asks what image
  a pod is running, how to see pod images, or how to change/update a
  service container image (e.g. the Neutron API one) in RHOSO.
---

# RHOSO Pod Images: Retrieve and Change

How to inspect the container image a RHOSO OpenStack pod is running, and
how to change it perdurably via the `OpenStackControlPlane` (OSCP) CR.

## Prerequisites

- Environment access: complete the connection steps in
  [rhoso-access/SKILL.md](../rhoso-access/SKILL.md) first (SSH to the
  baremetal node, then to `controller-0` as `zuul`, then `oc login`).
- The `oc` commands below run on the controller, logged into the OCP
  cluster.

# 1. How to See What Images Are Running

**All pods with their images** (the main command):

```bash
oc get pods -n openstack -o custom-columns="POD:.metadata.name,IMAGE:.spec.containers[*].image"
```

**Filter to one service**, e.g. Neutron:

```bash
oc get pods -n openstack -o custom-columns="POD:.metadata.name,IMAGE:.spec.containers[*].image" | grep neutron
```

**A single pod's image:**

```bash
oc get pod <pod-name> -n openstack -o jsonpath='{.spec.containers[*].image}'
```

`oc describe pod <pod-name> -n openstack` also shows the image and its
pull status.

**Image digests actually running** (useful to confirm a rollout finished):

```bash
oc get pod <pod-name> -n openstack -o jsonpath='{.status.containerStatuses[*].imageID}'
```

Note there are two namespaces:

| Namespace | Contents |
|-----------|----------|
| `openstack-operators` | OpenStack operators that define the services |
| `openstack` | OpenStack service workloads (the images of interest) |

# 2. How to Change a Pod Image (Perdurable)

In RHOSO, do **not** patch the Deployment or the service CR (e.g.
`NeutronApi`) directly: the operators reconcile them from the OSCP and
revert any change. The source of truth is the `OpenStackControlPlane` CR.

Patch the `containerImage` field under the service's `template`. Replace
`<oscp-name>` (usually `controlplane`), `<service>` (e.g. `neutron`,
`nova`, `glance`, `cinder`, `keystone`), and the image URL:

```bash
oc patch openstackcontrolplane <oscp-name> -n openstack --type merge -p '
spec:
  <service>:
    template:
      containerImage: <registry>/<repo>/<image>:<tag>
'
```

Example — change the Neutron API image:

```bash
oc patch openstackcontrolplane controlplane -n openstack --type merge -p '
spec:
  neutron:
    template:
      containerImage: quay.io/myrepo/openstack-neutron-server:my-tag
'
```

The service operator picks this up, updates the service CR (e.g.
`oc get neutronapi -n openstack`), and rolls out new pods with the new
image. The change survives reconciles.

## Verify the Change

```bash
oc get pods -n openstack -o custom-columns="POD:.metadata.name,IMAGE:.spec.containers[*].image" | grep <service>
oc rollout status deployment/<deployment-name> -n openstack
oc logs -f <new-pod-name> -n openstack
```

## Note for Code Testing

When the service code is mounted from a PVC (see the rhoso-code skill,
e.g. Neutron code at `/usr/lib/python3.9/site-packages/neutron`), changing
the image only matters when a different base image is needed (different
Python deps/RPMs). For pure Python code changes, updating the PVC contents
and restarting the pods is usually enough:

```bash
oc delete pod <pod-name> -n openstack
```

# Workflow Summary

```
Task Progress:
- [ ] Complete environment access (rhoso-access skill)
- [ ] List pod images: oc get pods -n openstack -o custom-columns=...
- [ ] Patch OSCP: spec.<service>.template.containerImage
- [ ] Wait for rollout and verify the new image is running
```

# Troubleshooting

- **Image not rolling out**: Check the operator logs
  (`oc get pods -n openstack-operators`, then `oc logs <operator-pod> -n openstack-operators`)
  and confirm the OSCP patch was applied
  (`oc get openstackcontrolplane -n openstack -o yaml | grep -A2 containerImage`).
- **ImagePullBackOff**: The registry/tag is wrong or not reachable from
  the cluster nodes. Check with `oc describe pod <pod-name> -n openstack`.
