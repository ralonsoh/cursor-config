---
name: rhoso-must-gather
description: >-
  Collect and analyze a full RHOSO must-gather: service and operator logs,
  configs, CRs, network resources, databases, SOS reports from OCP and EDPM
  nodes, and Guru Meditation Reports. Use when the user asks to collect
  logs/data from the whole environment, create a must-gather, dump OpenStack
  databases, or analyze a must-gather archive.
---

# RHOSO Must-Gather: Collect and Analyze

Collect a full snapshot of a RHOSO environment with
[openstack-must-gather](https://github.com/openstack-k8s-operators/openstack-must-gather),
then analyze it offline.

## Prerequisites

- Environment access: complete [rhoso-access/SKILL.md](../rhoso-access/SKILL.md)
  first (`oc` commands run on the controller, logged into OCP).
- The must-gather image:
  `quay.io/openstack-k8s-operators/openstack-must-gather`.

# Run the Collection

Basic collection (creates a local `must-gather.local.*` directory):

```bash
oc adm must-gather --image=quay.io/openstack-k8s-operators/openstack-must-gather
```

**Timing (verified)**: a collection without SOS reports or DB dumps takes
roughly 8 minutes on a devnest-scale environment — run it inside tmux or
with a generous timeout, and expect `oc adm must-gather` to clean up its
helper namespace (`openshift-must-gather-*`) when it finishes.

With databases and EDPM SOS reports:

```bash
oc adm must-gather --image=quay.io/openstack-k8s-operators/openstack-must-gather \
  -- OPENSTACK_DATABASES=ALL SOS_EDPM=all gather
```

The final result is archived as `must-gather.tar.xz` (or `must-gather.tar`
when SOS reports are kept compressed, i.e. `SOS_DECOMPRESS=0`).

## How the Collection Works

`oc adm must-gather` runs the `gather` entrypoint in a container on one node;
`gather_run` then orchestrates, in order:

1. **Guru Meditation Reports (GMR)** — signals oslo.reports dumps in cinder,
   nova and manila pods so the reports land in the collected pod logs
   (`gather_trigger_gmr`).
2. **SOS reports** — from OCP nodes running OpenStack pods and from EDPM
   nodes (via SSH). These run first as they are the slowest collectors.
3. **Namespaced resources** — either via `oc adm inspect` (OMC mode,
   default) or the legacy per-namespace collectors: pods (describe + logs,
   including `--previous` and init containers), events, PVCs, NADs,
   deployments/statefulsets/replicasets/jobs/cronjobs, services, routes,
   ConfigMaps (service config), Secrets (masked), CSVs, subscriptions,
   installplans.
4. **Backup/restore and OADP** resources.
5. **Database dumps** — `mysqldump --single-transaction` from the first
   galera pod (`-l app=galera,pods.kubernetes.io/pod-index=0`) per database.
6. **Service status** — runs `openstack` CLI commands inside the
   `openstackclient` pod per service (neutron, nova, cinder, manila, heat,
   placement, ironic, ...), e.g. agent lists and service catalogs.
7. Version logging of the tool itself, then compression.

## Debug Mode (Interactive Collection)

To keep the gathering container alive so you can inspect it or run
`/usr/bin/gather` manually with custom settings:

```bash
oc adm must-gather --image=quay.io/openstack-k8s-operators/openstack-must-gather -- /usr/bin/gather_debug
```

The container sleeps until `/tmp/rm-to-finish-gathering` is deleted. From
another terminal, `oc rsh` into the must-gather pod, explore, run
`/usr/bin/gather`, then `rm /tmp/rm-to-finish-gathering` to finish.

# Directory Layout

## OMC Mode (Default, Verified on RHOSO 18)

With `OMC=true` (default), resources are collected with `oc adm inspect`
into the standard Kubernetes/OpenShift structure, compatible with
[omc](https://github.com/gmeghnag/omc). Note the extra wrapper directory
named after the image (`oc adm must-gather` copies the image's output
under `must-gather.local.<id>/<image-dir>/`):

```
must-gather.local.<id>/
├── must-gather.tar.xz                # final archive of everything
├── must-gather.logs / gather.logs    # oc adm must-gather's own log
└── <image-name-sha256-...>/          # e.g. quay-io-openstack-k8s-operators-openstack-must-gather-sha256-...
    ├── run.log                       # full output of the gathering process
    ├── version                       # must-gather tool version
    ├── ctlplane/                     # per-service openstack CLI outputs
    │   ├── neutron/                  #   agent_list, network_list, port_list,
    │   │                             #   router_list, subnet_list, ...
    │   ├── nova/                     #   service_list, hypervisor_list, ...
    │   └── cinder/, glance/, manila/, designate/, ovn/, endpoints/
    ├── cluster-scoped-resources/
    │   ├── core/                     #   nodes, namespaces
    │   ├── admissionregistration.k8s.io/  # validating/mutating webhookconfigs
    │   ├── nmstate.io/               #   nodenetworkconfigurationpolicies,
    │   │                             #   ...enactments, ...states (NNCP/NNCE/NNS)
    │   └── apiextensions.k8s.io/     #   CRDs
    ├── namespaces/
    │   ├── openstack/                # per-namespace oc adm inspect tree
    │   │   ├── all_resources.log     #   oc get all
    │   │   ├── events.log            #   sorted by lastTimestamp
    │   │   ├── <group>/<resource>/   #   CRs grouped by API group
    │   │   └── pods/<pod>/
    │   │       ├── <pod>.yaml        #   pod manifest
    │   │       └── <container>/<container>/logs/
    │   │           ├── current.log           # current container log
    │   │           └── previous.insecure.log # previous (crashed) instance
    │   ├── openstack-operators/
    │   └── <other-namespaces>/       # metallb-system, openshift-nmstate, ...
    ├── sos-reports/
    │   └── _all_nodes/               # SOS reports from OCP (and EDPM) nodes,
    │                                 #   possibly .tar.xz per node
    └── dbs/                          # only with OPENSTACK_DATABASES set
        └── <namespace>/<galera-pod>-<service>.sql
```

The `ctlplane/` directory is a goldmine: `ctlplane/neutron/agent_list`
shows all agents (with alive/state), `ctlplane/nova/hypervisor_list` the
compute nodes, etc. — collected by running `openstack` CLI commands
inside the `openstackclient` pod.

## Legacy Mode (`OMC=false`)

OpenStack-specific structure (deprecated but still available):

```
<must-gather-root>/
├── run.log                           # full output of the gathering process
├── namespaces/
│   └── <ns>/
│       ├── all_resources.log         # oc get all
│       ├── events.log                # sorted by lastTimestamp
│       ├── pvc.log
│       ├── nad.log                   # network-attachment-definitions
│       └── pods/<pod>/
│           ├── <pod>-describe
│           └── logs/
│               ├── <container>.log
│               ├── <container>-previous.log   # if container restarted
│               └── <init-container>.log       # if init containers ran
├── network/
│   ├── nncp/<name>.yaml              # NodeNetworkConfigurationPolicies
│   ├── nnce/<name>.yaml              # NodeNetworkConfigurationEnactments
│   ├── nns/<name>.yaml               # NodeNetworkStates
│   ├── ipaddresspools/<name>.yaml    # MetalLB (metallb-system ns)
│   └── l2advertisement.yaml
├── sos-reports/_all_nodes/           # per-node sos report archives
├── dbs/<namespace>/<galera-pod>-<service>.sql
├── webhooks/
│   ├── validating/<name>.yaml
│   └── mutating/<name>.yaml           # caBundle stripped
└── version.txt
```

# Environment Variables

| Variable | Purpose |
|----------|---------|
| `OPENSTACK_DATABASES` | Comma-separated DBs to dump, or `ALL`. Default: skipped |
| `FILTER_DB_CELLS` | `true` to exclude cell databases. Default: `false` |
| `SOS_SERVICES` | Comma-separated services for OCP-node SOS reports; empty skips |
| `SOS_ONLY_PLUGINS` | SOS plugins to use; empty runs all |
| `SOS_COLLECT_ROTATED_POD_LOGS` | `1` to add the `container_log` sos plugin with rotated logs — the only source for kubelet-rotated pod logs that `oc logs` no longer serves |
| `SOS_EDPM` | EDPM nodes for SOS reports, e.g. `edpm-compute-0` or `all`; empty skips |
| `SOS_EDPM_PROFILES` | SOS profiles for EDPM (default `container,openstack_edpm,system,storage,virt`) |
| `SOS_EDPM_PLUGINS` | Restrict EDPM SOS to specific plugins |
| `SOS_EDPM_JOURNAL_SIZE` | Limit collected journals (MiB) |
| `OSP_NS` / `OSP_OPERATORS_NS` | Service/operator namespaces (default `openstack` / `openstack-operators`) |
| `ADDITIONAL_NAMESPACES` | Extra namespaces to gather |
| `METALLB_NAMESPACE` | MetalLB namespace (default `metallb-system`) |
| `OMC` | `true` (default): standard `oc adm inspect` layout; `false`: legacy layout |
| `CONCURRENCY` | Parallelism of background collectors (default 5) |
| `SOS_DECOMPRESS` | `1` to extract SOS reports; `0` keeps them as `.tar.xz` and bundles everything into a plain `must-gather.tar` |
| `DO_NOT_MASK` | `1` dumps secrets/configs unmasked (CI only — never in production) |
| `COMPRESSED_PATH` / `DELETE_AFTER_COMPRESSION` | Where to store the archive / delete raw data after |
| `SUPPORT_TOOLS` | Override the support-tools image (disconnected environments) |

Default namespaces gathered (plus `ADDITIONAL_NAMESPACES`): `openstack`,
`openstack-operators`, `baremetal-operator-system`, `openshift-machine-api`,
`cert-manager`, `openshift-nmstate`, `openshift-operators-redhat`,
`openshift-operators`, `openshift-logging`, `metallb-system`, `openshift-adp`.

# Analyze the Report

With [omc](https://github.com/gmeghnag/omc) (`go install github.com/gmeghnag/omc@latest`):

```bash
omc use <image-dir>              # the dir containing cluster-scoped-resources/
                                 # i.e. must-gather.local.<id>/<image-name-sha...>/
omc get nodes                    # sanity check
omc get pods -n openstack
```

Manual analysis workflow:

1. If the report is a `.tar.xz`, extract it first. Treat it as read-only.
2. Check `run.log` first: it mirrors the whole collection and shows which
   collectors ran or failed (e.g. "Skipping SOS gathering for EDPM nodes").
3. Scan for problems: `grep -riE "error|fail|fatal|restart" <root>`
   (ripgrep preferred on large reports).
4. Service-level state: `ctlplane/<service>/` (e.g.
   `ctlplane/neutron/agent_list` for agent liveness,
   `ctlplane/nova/service_list` for compute services).
5. Pod logs: `namespaces/openstack` (services) and
   `namespaces/openstack-operators` (operators). In OMC mode logs are at
   `pods/<pod>/<container>/<container>/logs/current.log` (and
   `previous.insecure.log` for the crashed instance).
6. Node-level and dataplane detail: `sos-reports/_all_nodes` (may need
   extraction from `.tar.xz`); EDPM compute sos reports are the place to
   look for VM and dataplane service problems.
7. Network issues: NNCP/NNCE/NNS at
   `cluster-scoped-resources/nmstate.io/` (OMC mode) or `network/`
   (legacy mode); IPAddressPools/L2Advertisements under the
   `metallb-system` namespace.
8. Database-level debugging: `dbs/` dumps (only if requested at collection).
9. GMR dumps (cinder/nova/manila) are inside the pod logs — search for
   "Guru Meditation" in the service pod logs.
10. Find the root cause, not symptoms; cite file paths in the output.
11. Ignore short transient errors — expected in convergence-oriented
    deployments where many things run in parallel.

For deeper triage, the openstack-k8s-operators `devskills` repo provides
`analyze-must-gather` and `support-triage` agent skills (see
[devskills](https://github.com/openstack-k8s-operators/devskills)).

# Workflow Summary

```
Task Progress:
- [ ] Complete environment access (rhoso-access skill)
- [ ] Choose collection options (databases? EDPM SOS? rotated logs?)
- [ ] Run oc adm must-gather with the desired env vars
- [ ] Extract the archive if tarballed
- [ ] Check run.log, then scan namespaces/ and sos-reports/ for errors
- [ ] Produce a structured analysis with file paths
```

# Troubleshooting

- **oc adm must-gather hangs**: a collector may be stuck (e.g. SSH to an
  EDPM node for SOS). Use the debug mode above to inspect the container.
- **Cannot find pod logs**: check `namespaces/<ns>/pods/`; rotated logs are
  only present if `SOS_COLLECT_ROTATED_POD_LOGS=1` was set at collection.
- **No database dumps**: `OPENSTACK_DATABASES` was unset — it is skipped by
  default; re-run with `OPENSTACK_DATABASES=ALL`.
- **No EDPM SOS reports**: `SOS_EDPM` was unset — also skipped by default.
- **omc not loading**: `omc use` needs the directory containing
  `cluster-scoped-resources/` — in OMC mode that is the image-named
  wrapper directory under `must-gather.local.<id>/`. Find it with
  `find <path> -maxdepth 3 -name cluster-scoped-resources -type d`.
