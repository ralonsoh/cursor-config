---
name: rhoso-ctlplane-debug
description: >-
  Debug the RHOSO control plane: OpenStackControlPlane readiness, service CR
  conditions, operator health, pod troubleshooting, RabbitMQ, MariaDB, and
  network attachment debugging. Use when the control plane is not Ready, a
  service CR reports failures, operators misbehave, pods crash, or the user
  asks how to debug the control plane or a specific control plane service.
---

# RHOSO Control Plane Debugging

Source: [dev-docs troubleshooting](https://github.com/openstack-k8s-operators/dev-docs/blob/main/troubleshooting.md)
and the operator repos. All commands run with `oc` on the controller, logged
into the cluster (see [rhoso-access/SKILL.md](../rhoso-access/SKILL.md)).

## Prerequisites

- Environment access: complete [rhoso-access/SKILL.md](../rhoso-access/SKILL.md) first.

# The Debug Ladder

Always debug top-down: OSCP → service CR → operator → pods → containers.
Each level's message tells you where to look next.

## 1. OpenStackControlPlane Status

```bash
oc get openstackcontrolplane -n openstack
```

If `STATUS` is not `True`, the `MESSAGE` names the failing part. Drill in:

**List every condition that is not True (note: `{range`, not `{.range`):**

```bash
oc get -n openstack OpenStackControlPlane \
  -o jsonpath="{range .items[0].status.conditions[?(@.status!='True')]}{.type} is {.status} due to {.message}{'\n'}{end}"
```

**Check the Ready condition in detail:**

```bash
oc get -n openstack OpenStackControlPlane \
  -o jsonpath="{.items[0].status.conditions[?(@.type=='Ready')]}" | jq
```

**Individual service deployment status within the OSCP:**

```bash
oc get openstackcontrolplane -n openstack -o yaml | grep -A2 'deployedVersion\|ready\|readyCount'
```

**List all OpenStack CRs and their instances at once:**

```bash
oc get $(oc api-resources --api-group=core.openstack.org -o name | tr '\n' ',' | sed 's/,$//') -n openstack 2>/dev/null
```

## 2. Service CR Conditions

If the OSCP reports a service not Ready (e.g.
`OpenStackControlPlaneNovaReady` is False), check that service's CR.
**The CR type names differ from the OSCP spec keys** — verified on RHOSO 18:

```bash
oc get -n openstack nova/nova \
  -o jsonpath="{range .status.conditions[?(@.status!='True')]}{.type} is {.status} due to {.message}{'\n'}{end}"
```

Verified CR types: `nova`, `keystoneapi`, `glance`, `cinder`,
`neutronapi`, `placement`, `heat`, `ironic`, `designate`, `manila`,
`swift`, `watcher`, `ovndbcluster`, `galera` (not `mariadb` — renamed in
RHOSO 18), `rabbitmq` (not `rabbitmqclusters`), `memcached`,
`openstackclient`. CR instance names vary (`nova`, `keystone`,
`glance-f9d89`, `cinder-c5efc`, ...) — list them with the command from
step 1, e.g. `oc get glance -n openstack`.

## 3. Operator Health

The operators run in `openstack-operators` and are labelled:

```bash
oc get pods -n openstack-operators -l openstack.org/operator-name=nova
oc logs -n openstack-operators -l openstack.org/operator-name=nova
```

**Operator installation state (OLM):**

```bash
oc get csv -n openstack-operators                     # per-operator version/phase
oc get subscriptions -n openstack-operators           # channel/upgrade state
oc get installplans -n openstack-operators
oc get operatorgroup -n openstack-operators
```

**Operator conditions and events:**

```bash
oc get events -n openstack-operators --sort-by='.lastTimestamp' | tail -30
```

## 4. Service Pods

```bash
oc get pods -n openstack | grep <service>
oc describe pod <pod-name> -n openstack
oc logs <pod-name> -n openstack
oc logs --previous <pod-name> -n openstack     # crashed container's last logs
```

**Crashing pods (CrashLoopBackOff):** `oc rsh` is impossible; duplicate the
pod without its command, probes, and labels:

```bash
oc debug pod/<pod-name>
```

- `--keep-labels=true` keeps the duplicate as a Service backend (route
  traffic to it).
- Also works on pod-creating resources and nodes:
  `oc debug StatefulSet/cinder-scheduler`, `oc debug node/<node>`.

**Exec into a running pod:**

```bash
oc rsh <pod-name> -n openstack
oc exec -n openstack <pod> -c <container> -- <command>
```

**Pod images and pull failures** — see the
[rhoso-openstack-image](../rhoso-openstack-image/SKILL.md) skill.

# Service-Specific Debugging

## MariaDB / Galera

The databases back everything; if the DB is down, all services fail.
The CR type is `galera` in RHOSO 18 (not `mariadb`):

```bash
oc get galera -n openstack
oc get pods -n openstack -l app=galera
oc logs -n openstack <galera-pod> -c galera
```

Check a database directly from the first galera pod:

```bash
oc exec -n openstack -c galera <galera-pod> -- mysql -u root -e "SHOW DATABASES;"
oc exec -n openstack -c galera <galera-pod> -- mysql -u root -e "USE neutron; SHOW TABLES;"
```

Useful WSREP status queries:

```sql
SHOW STATUS LIKE 'wsrep_cluster_size';
SHOW STATUS LIKE 'wsrep_ready';
SHOW STATUS LIKE 'wsrep_local_state_comment';  -- Synced is healthy
```

MariaDB/galera CR conditions (`oc get galera openstack -o yaml`) report
the galera replication state.

## RabbitMQ

Message bus for all services. Selector:
`app.kubernetes.io/component=rabbitmq`.

```bash
oc get pods -n openstack -l app.kubernetes.io/component=rabbitmq
oc get rabbitmq -n openstack              # RHOSO 18 CR type (not rabbitmqclusters)
oc logs -n openstack <rabbitmq-pod>
```

Check queue health with rabbitmqctl inside a pod:

```bash
oc exec -n openstack <rabbitmq-pod> -- rabbitmqctl cluster_status
oc exec -n openstack <rabbitmq-pod> -- rabbitmqctl list_queues name messages consumers
```

Unacked-message pile-ups or down exchanges explain services stuck waiting
for RPC replies.

## OVN

The OVN control plane (northbound/southbound databases, ovn-northd) runs as
pods; ovn-controller runs on the EDPM nodes.

```bash
oc get ovndbcluster -n openstack          # NB and SB cluster state
oc get ovncontrollers -n openstack        # per-node ovn-controller
oc get pods -n openstack | grep ovn
oc logs -n openstack ovn-controller-... 
```

`ovndbcluster` short conditions report NB/SB cluster and database health.

## Keystone

Endpoints and auth for everything. If Keystone is broken, every service
shows auth errors:

```bash
oc get keystoneapi -n openstack
oc get routes -n openstack | grep keystone
```

## Network Attachments (pod networks)

Control plane pods attach to isolation networks (internalapi, storage, ...)
via NetworkAttachmentDefinitions; a missing attachment shows pods stuck in
`ContainerCreating`:

```bash
oc get network-attachment-definitions -n openstack
oc get network-attachment-definitions -n openstack -o yaml > /tmp/nad.yaml
oc describe pod <pod> -n openstack     # shows FailedMount / Multus errors
```

## Memcached

```bash
oc get memcached -n openstack
oc get pods -n openstack | grep memcached
```

# Common Control Plane Failure Patterns

| Symptom | First places to look |
|---------|----------------------|
| OSCP not Ready | OSCP conditions → failing service CR → its operator logs |
| Pod in CrashLoopBackOff | `oc logs --previous`, `oc debug pod/...` |
| Pod stuck Pending | `oc describe pod` → unschedulable, PVC pending, missing NAD |
| ImagePullBackOff | `oc describe pod` image events; wrong tag/registry |
| All services failing RPC | RabbitMQ cluster status; unacked queues |
| All services failing DB | MariaDB/galera `wsrep_local_state_comment`; PVC state |
| Auth errors everywhere | Keystone pods/routes; certificates expiry |
| Webhook errors on CR apply | `oc get validatingwebhookconfigurations`; operator pods |
| Reconcile loop thrashing | Operator logs; repeated `Requeue`/conflict messages |

# Workflow Summary

```
Task Progress:
- [ ] Complete environment access (rhoso-access skill)
- [ ] oc get openstackcontrolplane: read the failing condition message
- [ ] Drill into the failing service CR conditions
- [ ] Check the service operator pods/logs
- [ ] Check the service pods (describe, logs, --previous, oc debug)
- [ ] Check shared infra if multiple services fail: MariaDB, RabbitMQ, Keystone
- [ ] For bulk collection: rhoso-must-gather skill
```

# Troubleshooting

- **OSCP stuck "in progress"**: a service CR condition shows the blocker;
  if all conditions are True but the OSCP is not Ready, check the
  openstack-operator (meta-operator) logs in `openstack-operators`.
- **Conditions flap**: read `lastTransitionTime` on the conditions to see
  whether it is a stable failure or a reconcile loop.
- **Need a full snapshot**: use the [rhoso-must-gather](../rhoso-must-gather/SKILL.md)
  skill (optionally with `OPENSTACK_DATABASES=ALL`).
- **Suspect operator bug**: use devskills `debug-operator` for automated
  log-pattern analysis, and the
  [dev-docs](https://github.com/openstack-k8s-operators/dev-docs/blob/main/troubleshooting.md)
  for running the operator locally with delve.
