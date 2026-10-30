---
name: rhoso-edpm-debug
description: >-
  Debug the RHOSO data plane (EDPM) nodes: deployment and NodeSet conditions,
  AnsibleEE jobs and execution summaries, SSH access to nodes, node-level
  services (ovn-controller, nova-compute, podman containers), and re-running
  services with ansible tags/limits. Use when a data plane deployment fails,
  an EDPM node is unreachable, a dataplane service misbehaves, or the user
  asks how to debug or access EDPM/compute nodes.
---

# RHOSO Data Plane (EDPM) Debugging

Sources: [openstack-operator dataplane docs](https://github.com/openstack-k8s-operators/openstack-operator/tree/main/docs/assemblies)
(`interacting_with_ansible.adoc`, `proc_troubleshooting-data-plane-creation-and-deployment.adoc`,
`ref_data-plane-conditions-and-states.adoc`, `logs.adoc`),
[edpm-ansible](https://github.com/openstack-k8s-operators/edpm-ansible).

## Prerequisites

- Environment access: complete [rhoso-access/SKILL.md](../rhoso-access/SKILL.md) first.
- The data plane nodes are managed by Ansible Execution Environment (AnsibleEE)
  jobs spawned by the dataplane operator; every service on a node
  (nova-compute, ovn-controller, telemetry, ...) is deployed/configured by an
  ansible play, run inside a Job pod.

# Understand the Resources

| Resource | Purpose |
|----------|---------|
| `OpenStackDataPlaneNodeSet` | A set of EDPM nodes with their services, networks, and ansible config |
| `OpenStackDataPlaneDeployment` | A deployment (ansible execution) over one or more NodeSets |
| `OpenStackDataPlaneService` | A composable service (an ansible execution managing software on nodes) |
| `OpenStackAnsibleEE` | The CR representing each ansible execution job (older releases; on RHOSO 18 there is no queryable `openstackansibleee` resource — use jobs and labels, below) |

Default NodeSet services (when `services` is omitted): `redhat`,
`download-cache`, `bootstrap`, `configure-network`, `validate-network`,
`install-os`, `configure-os`, `run-os`, `libvirt`, `nova`, `ovn`,
`neutron-ovn`, `telemetry`.

# 1. Deployment Status

**All deployments:**

```bash
oc get openstackdataplanedeployment
oc get openstackdataplanenodeset
```

The `MESSAGE` column names the failing part, e.g.
`Deployment error occurred nodeSet: openstack-edpm-ipam error: execution.name telemetry-edpm-deployment-... Execution.status.jobstatus: Failed`.

**All service jobs and their conditions (per deployment).** On RHOSO 18
there is no `openstackansibleee` resource to query — list the Jobs
directly with the deployment label:

```bash
oc get job -l openstackdataplanedeployment=<deployment-name>
```

For each job, `oc get job <name>` shows the completion status, and the
job's pod conditions carry the state. Failing job pods report:
`openstackansibleee job <POD_NAME> failed due to <ERROR> with message:
<ERROR_MSG>`.

# 2. Conditions and Execution Summaries

**NodeSet conditions:**

| Condition | Meaning when True |
|-----------|-------------------|
| `Ready` | NodeSet successfully deployed |
| `DeploymentReady` | Deployment succeeded |
| `InputReady` | Required inputs available |
| `SetupReady` | Setup tasks done (SSH key secret verified, ansible inventory created) |
| `NodeSetIPReservationReady` | IPSet resources ready |
| `NodeSetDNSDataReady` | DNSData resources ready |
| `NodeSetBaremetalProvisionReady` | Bare metal nodes provisioned |

Note: `Ready` flips to `False` while a new deployment runs, back to `True`
on success.

**Deployment conditions:** `Ready`, `DeploymentReady`, `InputReady`, plus
per-NodeSet `<NodeSet> Deployment Ready` and per-service
`<NodeSet> <Service> Deployment Ready` conditions — the latter show exactly
which service on which NodeSet failed.

**Execution summaries** (failed/unreachable hosts per job, recorded in the
NodeSet status):

```bash
oc get openstackdataplanenodeset <nodeset> -o json | jq '.status.deploymentExecutionSummaries'
```

Each entry has `totalHosts`, `failedHosts`, `unreachableHosts`,
`failurePercent`, `failedHostList`, `unreachableHostList`.

# 3. Job Logs

Every dataplane service execution is a Kubernetes Job:

```bash
oc get job -l openstackdataplanedeployment=<deployment-name>
oc logs -f job/<job-name>
```

The PLAY RECAP at the end shows `ok/changed/unreachable/failed` per node.
For persistent ansible artifacts (requires `extraVolType: Logs` extraMounts
on a PVC at `/runner/artifacts` in the NodeSet):

```bash
oc get pods -l app=openstackansibleee
oc rsh <ansibleee-pod>            # or: oc debug <pod> when not running
ls /runner/artifacts
cat /runner/artifacts/<service>/stdout
```

# 4. Interactive Re-run with Modified Inventory

Debug a failing job interactively — duplicate it and run ansible-runner
yourself:

```bash
oc debug --as-root --keep-annotations job/<execution-name>
```

Inside the debug pod (working dir `/runner`; edpm-ansible collection at
`/usr/share/ansible/collections/ansible_collections/osp/edpm`):

```bash
/opt/builder/bin/edpm_entrypoint ansible-runner run /runner \
  -p osp.edpm.<service> -i <execution-name>
```

Modify the inventory for debugging:

```bash
cp /runner/inventory/hosts /root/inventory
microdnf -y install vim
# edit /root/inventory, then re-run with --inventory /root/inventory
/opt/builder/bin/edpm_entrypoint ansible-runner run /runner \
  -p osp.edpm.<service> -i <execution-name> --inventory /root/inventory
```

# 5. SSH into the EDPM Nodes

The nodes are managed over SSH by the ansible jobs, using the SSH key
stored in a Secret (name from the NodeSet's
`spec.nodeTemplate.ansibleSSHPrivateKeySecret`, typically
`dataplane-ansible-ssh-private-key-secret`) — the same key gives you
direct node access. Node IPs come from each node's
`spec.nodes.<node>.ansible.ansibleHost` or the IPAM `ipset` reservations:

```bash
# Find the key secret name and node entries
oc get openstackdataplanenodeset <nodeset> -o json | jq '.spec.nodeTemplate.ansibleSSHPrivateKeySecret, .spec.nodes'
oc get ipset -n openstack                    # IPAM nodes
oc get ipset <node> -n openstack -o json | jq '.status.reservations'   # ctlplane IP

# Extract the private key and connect
oc get secret -n openstack <ssh-secret-name> -o jsonpath='{.data.ssh-privatekey}' | base64 -d > /tmp/edpm_key
chmod 600 /tmp/edpm_key
ssh -i /tmp/edpm_key zuul@<node-ip>
```

Verified on a devnest environment: user `zuul` with the
`dataplane-ansible-ssh-private-key-secret` key works, and `sudo -n` is
passwordless. On installed environments the user is typically
`cloud-admin` or `root`. In devnest-style environments the node
inventory is also visible from the baremetal host's
`/etc/cifmw-dnsmasq.d/dhcp-hosts.d/` files (see rhoso-access).

**Ad-hoc ansible against the nodes:** create an `AnsibleEE` CR running your
own playbook/inventory (examples in the
[openstack-ansibleee-operator](https://github.com/openstack-k8s-operators/openstack-ansibleee-operator)
repo).

# 6. On-Node Debugging

Once on an EDPM node, the OpenStack services run as **podman containers**:

```bash
sudo podman ps -a                      # all containers, incl. exited (sudo needed as zuul)
sudo podman logs <container>
sudo podman exec -it <container> bash
systemctl status edpm-deploy         # node deployment service (if used)
```

Verified container names on a devnest compute node: `ovn_controller`,
`ovn_metadata_agent`, `nova_compute`.

**Key services to check:**

- **ovn-controller**: `podman logs ovn_controller`, unixctl socket at
  `/run/ovn/ovn-controller.<pid>.ctl` (see
  `ovn-appctl -t /run/ovn/ovn-controller.<pid>.ctl ...`)
- **nova-compute**: `podman logs nova_compute`, logs also under
  `/var/log/containers/nova/`
- **OVS**: `ovs-vsctl show`, `ovs-ofctl dump-flows <bridge>`, db socket
  `/run/openvswitch/db.sock`
- **neutron metadata agent** (from the `neutron-ovn` service)
- **libvirt**: `virsh list --all` for instances on the node

Node-level sos reports can be collected with the must-gather skill
(`SOS_EDPM=all`), with EDPM profiles
(`container,openstack_edpm,system,storage,virt`).

**Network checks on the node:**

```bash
ip addr; ip route                      # ctlplane and data networks
sudo ovs-vsctl show                    # bridges and ports
ping <other-node-ctlplane-ip>
```

Also compare against the requested state in the must-gather's
`network/nncp`/`nnce`/`nns` YAMLs or `oc get nncp -o yaml` on the cluster.

# 7. Control Re-runs

Re-run selected services or nodes via `OpenStackDataPlaneDeployment` fields
(syntax matches the `ansible-playbook` CLI):

```yaml
apiVersion: dataplane.openstack.org/v1beta1
kind: OpenStackDataPlaneDeployment
metadata:
  name: openstack-edpm
spec:
  nodeSets: ["openstack-edpm"]
  ansibleTags: containers             # --tags
  ansibleSkipTags: packages           # --skip-tags
  ansibleLimit: compute1*,compute2*   # --limit
```

Applying a new deployment CR referencing the NodeSet triggers the re-run.

# 8. Testing Local edpm-ansible Changes

1. **Volume-mount a local copy into ansibleee pods** (fastest, no image
   rebuild — see the
   [edpm-ansible docs](https://openstack-k8s-operators.github.io/edpm-ansible/)).
2. **Build a custom runner image**:

```bash
export IMAGE_TAG_BASE=quay.io/<user>/openstack-ansibleee-runner
make openstack_ansibleee_build
make openstack_ansibleee_push    # podman login may be required
```

Role tests: `make execute_molecule` (via ci-framework, requires podman) or
`molecule test --all` inside `roles/<role>`.

# Workflow Summary

```
Task Progress:
- [ ] Complete environment access (rhoso-access skill)
- [ ] oc get openstackdataplanedeployment / nodeset: read the MESSAGE
- [ ] oc get job -l openstackdataplanedeployment=...: find the failing service job
- [ ] oc logs job/<name>: read PLAY RECAP for the failing node
- [ ] Check deploymentExecutionSummaries for failed/unreachable hosts
- [ ] oc debug job/<name> for an interactive ansible re-run
- [ ] SSH into the failing node with the ansible SSH key
- [ ] On the node: podman ps/logs, ovn-controller, OVS, nova-compute
- [ ] Re-run with ansibleTags/ansibleLimit as needed
```

# Troubleshooting

- **Node unreachable (`unreachableHosts`)**: check the node's ctlplane IP
  (`oc get ipset`), SSH key secret, and from the cluster/baremetal host,
  ping/SSH the node directly.
- **`SetupReady` False**: the SSH key secret is missing/invalid or the
  ansible inventory could not be generated — check the dataplane-operator
  logs in `openstack-operators`.
- **Network config failed**: the `configure-network`/`validate-network`
  jobs' PLAY RECAP plus the node's `ip addr`/`ovs-vsctl show` show the
  discrepancy; NNCP/NNCE enactments (`oc get nnce`) show per-node status.
- **Need node-level logs from all nodes at once**: use the
  [rhoso-must-gather](../rhoso-must-gather/SKILL.md) skill with
  `SOS_EDPM=all`.
- **Job pod itself failing to start**: `oc describe pod <job-pod>` — check
  the network attachment (`ctlplane`) and the EE image pull.
