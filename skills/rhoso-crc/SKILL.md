---
name: rhoso-crc
description: >-
  Deploy a full RHOSO 18.0 environment on CRC (CodeReady Containers) on a
  remote baremetal host: host prerequisites, pull secret, CRC VM, OpenStack
  control plane, and EDPM compute/networker nodes via install_yamls. Use when
  the user asks to deploy CRC, deploy RHOSO on CRC, create a CRC-based
  OpenStack environment, or mentions rhoso-crc, install_yamls make targets,
  or EDPM nodes on CRC.
---

# RHOSO on CRC deployment

Deploys OpenStack Services on OpenShift (RHOSO 18.0) inside a single CRC VM
plus EDPM VMs, on a remote lab host, using
[install_yamls](https://github.com/openstack-k8s-operators/install_yamls).

## Information to request before starting

Ask the user (use AskQuestion) for anything not already known:

1. **Target host** — SSH alias from `~/.ssh/config`. Requirements: RHEL 9.x,
   >= 24 free CPUs, >= 96 GB free RAM, >= 400 GB
   free disk, no conflicting running VMs (`virsh --connect qemu:///system
   list --all`).
2. **Pull secret** — JSON from
   https://console.redhat.com/openshift/create/local. MUST contain a valid
   `registry.redhat.io` entry; test it (see Step 0) before deploying.
   A pull secret known to work on another host may be reused.
3. **Sizing (defaults in parentheses)**: CRC CPUs (16), CRC memory in GB
   (64), CRC disk GB (200), number of computes (0 — EDPM optional),
   number of networkers (0), per-node VCPUs (8), RAM GB (24 compute /
   24 networker), disk GB (75).
4. **Deployment user** (default `ospng`) — created with passwordless sudo
   and SSH key access.

Do not start CRC deployment until the pull secret passes the validation in
Step 0. An invalid `registry.redhat.io` entry blocks `make openstack` with
openshift-marketplace catalog pods in `ImagePullBackOff`.

## Connection pattern

Use the `remote-vm` skill pattern: all commands on the target host run in a
tmux session named `cursor` (create as root if needed, then use
`su - <user> -c '...'` inside it, or create the session as the deployment
user). Long-running `make` steps: launch non-blocking, poll the log file for
an EXIT/DONE marker. The user watches with `tmux attach -t cursor`.

## Workflow

```
Task Progress:
- [ ] Step 0: Validate host + pull secret
- [ ] Step 1: Host prerequisites (packages, deployment user)
- [ ] Step 2: Pull secret + clone install_yamls + download_tools
- [ ] Step 3: Deploy CRC
- [ ] Step 4: Login + attach default interface
- [ ] Step 5: EDPM VMs (optional; computes and/or networkers)
- [ ] Step 6: Control plane (crc_storage, input, openstack, openstack_init, openstack_deploy)
- [ ] Step 7: EDPM dataplane deployment
- [ ] Step 8: Verification
- [ ] Teardown (destructive; separate procedure below)
```

### Step 0: Validate host + pull secret

```bash
# host checks
nproc; free -g; df -h /
virsh --connect qemu:///system list --all        # resources + no conflicts
dnf repolist                                     # beaker repos or registered

# pull secret validation (decodes registry.redhat.io auth and logs in)
AUTH=$(python3 -c "import json,base64; d=json.load(open('pull-secret.txt')); print(base64.b64decode(d['auths']['registry.redhat.io']['auth']).decode())")
echo "$AUTH" | cut -d: -f2- | podman login registry.redhat.io -u "$(echo "$AUTH" | cut -d: -f1)" --password-stdin
# expect: Login Succeeded!
```

If login fails, stop and ask the user for a fresh pull secret. A malformed
username like `|uhc-pool-...` (empty account part) means a bad copy.

### Step 1: Host prerequisites

```bash
dnf -y install ansible-core git golang libguestfs-tools dbus-x11 \
    libvirt libvirt-daemon libvirt-client qemu-kvm qemu-img libxml2 jq \
    virt-install make podman tmux
systemctl start libvirtd && systemctl enable libvirtd

id <user> 2>/dev/null || useradd <user>
echo '<user> ALL = (ALL) NOPASSWD: ALL' > /etc/sudoers.d/<user>
chown root:root /etc/sudoers.d/<user>; chmod 0600 /etc/sudoers.d/<user>
loginctl enable-linger <user>
mkdir -p /home/<user>/.ssh; chmod 0700 /home/<user>/.ssh
cp /root/.ssh/authorized_keys /home/<user>/.ssh/   # only useful if it holds a key the user can SSH with
chown -R <user>: /home/<user>/.ssh; chmod 0600 /home/<user>/.ssh/authorized_keys
```

Note: `libxml2` (xmllint) and `jq` are required by install_yamls scripts but
often missing from older runbooks.

### Step 2: Pull secret + repo + tools (as deployment user)

```bash
echo '<pull secret json>' > ~/pull-secret.txt && chmod 600 ~/pull-secret.txt
git clone https://github.com/openstack-k8s-operators/install_yamls ~/install_yamls
cd ~/install_yamls/devsetup && make download_tools   # installs crc/oc/etc into ~/bin
```

### Step 3: Deploy CRC (~20-40 min)

```bash
cd ~/install_yamls/devsetup
PULL_SECRET=$HOME/pull-secret.txt CPUS=<cpus> MEMORY=<mem> DISK=<disk> make crc
```

### Step 4: Login + attach interface

```bash
eval $(crc oc-env)            # REQUIRED: puts oc in PATH for all later steps
# NOTE: the line is `KUBEADMIN_PWD ?= <pwd>` — `cut -d= -f2` keeps the leading
# space and oc login then fails with "Only the server URL may be specified".
KPWD=$(sed -n 's/^KUBEADMIN_PWD.*=[[:space:]]*//p' ~/install_yamls/.secrets.env | tr -d '"')
oc login -u kubeadmin -p "$KPWD" https://api.crc.testing:6443
make crc_attach_default_interface
```

The kubeadmin password is auto-generated into `.secrets.env` — never assume
a hardcoded one.

`crc_attach_default_interface` may end with
`error: Requested operation is not valid: there is an existing dhcp host
entry in network 'default'` on a **re-deploy** over a host whose libvirt
`default` network was never wiped. Harmless if
`virsh --connect qemu:///system domifaddr crc` already shows
`192.168.122.10` — the interface is attached. To clear it before redeploying:
`virsh --connect qemu:///system net-update default delete ip-dhcp-host
"<host mac='52:54:00:11:11:10' ip='192.168.122.10'/>" --config --live`.

### Step 5: EDPM VMs (optional, as deployment user, in devsetup/)

`make edpm_compute` / `make edpm_networker` shell out to `oc` (via
`scripts/gen-ansibleee-ssh-key.sh`, which creates the ansible SSH key secret).
Without `oc-env` they die with a bare `make: *** Error 127` and no useful
message. Export it first:

```bash
eval $(crc oc-env)          # REQUIRED: gen-ansibleee-ssh-key.sh calls bare oc
cd ~/install_yamls/devsetup
export EDPM_TOTAL_NODES=<n>
EDPM_COMPUTE_VCPUS=4 EDPM_COMPUTE_RAM=16 EDPM_COMPUTE_DISK_SIZE=75 make edpm_compute
# networkers (IPs start at 192.168.122.200; computes at .100 — no collision):
export EDPM_TOTAL_NETWORKERS=<m>
EDPM_COMPUTE_VCPUS=4 EDPM_COMPUTE_RAM=8 EDPM_COMPUTE_DISK_SIZE=75 make edpm_networker
```

Note `EDPM_COMPUTE_*` variables apply to networkers too (there is no separate
`EDPM_NETWORKER_RAM`); set them again on the `edpm_networker` line if the
networkers need a different size.

### Step 6: Control plane (~30-50 min)

```bash
cd ~/install_yamls    # repo ROOT, not devsetup
PV_NUM=100 make crc_storage    # 100 local-storage PVs for stateful services
make input                     # secrets/ConfigMaps (admin pwd, SSH keys, TLS)
make openstack                 # OLM install of openstack-operator (needs registry auth)
make openstack_init            # OpenStack CR: deploys all service operators
make openstack_deploy          # OpenStackControlPlane CR: deploys the services
# if oc wait times out or make returns while conditions converge:
oc wait openstackcontrolplane openstack-galera-network-isolation -n openstack \
    --for condition=Ready --timeout=40m
```

### Step 7: EDPM dataplane deployment

```bash
# computes only:
DATAPLANE_TOTAL_NODES=<n> make edpm_wait_deploy   # 30m oc wait may time out!
DATAPLANE_TOTAL_NODES=<n> make edpm_nova_discover_hosts

# with networkers — KNOWN ISSUES, see Troubleshooting:
# 1. edpm_deploy_networker references out/operator/dataplane-operator/... (missing on master)
ln -sfn ~/install_yamls/out/operator/openstack-operator ~/install_yamls/out/operator/dataplane-operator
DATAPLANE_TOTAL_NETWORKER_NODES=<m> make edpm_deploy_networker
# 2. it REPLACES the deployment nodeSets (spec is immutable); recreate with both:
oc delete openstackdataplanedeployment edpm-deployment -n openstack
cat <<EOF | oc apply -f -
apiVersion: dataplane.openstack.org/v1beta1
kind: OpenStackDataPlaneDeployment
metadata:
  name: edpm-deployment
  namespace: openstack
spec:
  nodeSets:
  - openstack-edpm-ipam
  - openstack-edpm-ipam-networker
EOF
# wait for both:
oc wait openstackdataplanenodeset openstack-edpm-ipam -n openstack --for condition=Ready --timeout=40m
oc wait openstackdataplanenodeset openstack-edpm-ipam-networker -n openstack --for condition=Ready --timeout=40m
make edpm_nova_discover_hosts
```

### Step 8: Verification

```bash
oc get openstackcontrolplane -n openstack                     # STATUS True
oc get openstackdataplanenodeset -n openstack                 # all True
oc rsh openstackclient openstack compute service list -c Host -c Binary -c Status -f value
oc rsh openstackclient openstack network agent list -c Binary -c Host -c Alive -f value
# networkers run ovn-controller but NOT neutron-ovn-agent/nova-compute — that is correct
```

## Teardown

Destructive and irreversible. Verified end-to-end on RHEL 9.4.

Run as the deployment user on the target host. Two environment settings are
mandatory for the steps below and are the cause of silent failures if
omitted:

```bash
# 1. oc must be on PATH: the devsetup node-cleanup scripts call bare `oc`
#    and otherwise fail *silently*, leaving stale agents/nova services.
#    Path is ~/bin/crc, NOT ~/.crc/bin — `which crc` must resolve first.
eval $(crc oc-env)
# 2. virsh must target the system URI: install_yamls creates the domains as
#    root under qemu:///system, so a plain `virsh list` shows nothing.
export VIRSH_DEFAULT_CONNECT_URI=qemu:///system
```

Pre-flight: confirm there is something to tear down. If `virsh list --all`
is empty and `~/.crc/machines/crc/*.qcow2` does not exist, the environment is
already gone — skip to the residue checks below (steps are idempotent, so
re-running is harmless but pointless).

Order matters: the dataplane deployment must go before its nodeSets, and the
EDPM VMs before CRC.

The upstream `make` targets do NOT handle five things — see the notes after
the steps: networker nodeSets, node counts defaulting to 1, the
`confirm-delete` annotation, the ineffective agent purge, and — the most
damaging one — orphaned StatefulSets if the namespace is not deleted before
the operator.

### Step 1: Undeploy the dataplane (deployment, then nodeSets)

Each command is tolerant of already-missing objects, so this step is safe to
re-run on a partially torn-down environment.

```bash
cd ~/install_yamls
# A *running* deployment is protected by an admission webhook; annotate first.
# --ignore-not-found / 2>/dev/null make both calls no-ops if it is already gone.
oc annotate openstackdataplanedeployment edpm-deployment -n openstack \
    dataplane.openstack.org/confirm-delete=true --overwrite 2>/dev/null || true
oc delete openstackdataplanedeployment edpm-deployment -n openstack \
    --ignore-not-found --timeout=10m
oc wait --for=delete openstackdataplanedeployment/edpm-deployment \
    -n openstack --timeout=10m 2>/dev/null || true

make edpm_deploy_cleanup        # removes computes only (networkers: see below)
oc delete openstackdataplanenodeset openstack-edpm-ipam-networker \
    -n openstack --ignore-not-found
```

### Step 2: Destroy the EDPM VMs (counts are mandatory)

Set the counts to match the topology you deployed; they are **not detected**
and default to 1 each. Use the numbers from the deployment, e.g. the
`EDPM_TOTAL_NODES` / `EDPM_TOTAL_NETWORKERS` you passed to `make
edpm_compute` / `make edpm_networker`:

```bash
cd ~/install_yamls/devsetup
EDPM_TOTAL_NODES=<computes> make edpm_compute_cleanup
EDPM_TOTAL_NETWORKERS=<networkers> make edpm_networker_cleanup
virsh list --all                # only crc should remain (qemu:///system!)
```

Example for a 2-compute / 2-networker topology:

```bash
EDPM_TOTAL_NODES=2 make edpm_compute_cleanup
EDPM_TOTAL_NETWORKERS=2 make edpm_networker_cleanup
```

The scripts print `error: Storage volume 'vda' ... is not managed by libvirt`
for each node — benign; the qcow2 is removed by the script itself.

### Step 3: Purge the stale EDPM agents (REQUIRED)

`edpm_deploy_cleanup` in Step 1 deletes the network agents *before* the VMs
die, so the still-running `ovn-controller`s simply re-register and you are
left with dead agent rows that break the next deployment. Purge after the VMs
are gone:

```bash
# network agents (compute + networker, both ovn-controller and neutron-ovn-agent)
AGENTS=$(oc rsh openstackclient bash -c \
  "openstack network agent list -f value -c ID -c Host \
   | grep -E 'edpm-(compute|networker)-' | awk '{print \$1}' | xargs echo -n")
[ -n "$AGENTS" ] && oc rsh openstackclient bash -c "openstack network agent delete $AGENTS"

# nova-compute services left in 'down' state
SVCS=$(oc rsh openstackclient bash -c \
  "openstack compute service list -f value -c ID -c Host --service nova-compute \
   | grep -E 'edpm-' | awk '{print \$1}' | xargs echo -n")
[ -n "$SVCS" ] && oc rsh openstackclient bash -c "openstack compute service delete $SVCS"

# expect: only `crc` ovn-controller and the 3 control-plane nova services remain
oc rsh openstackclient openstack network agent list -c Binary -c Host -c Alive -f value
oc rsh openstackclient openstack compute service list -c Host -c Binary -f value
```

### Step 4: Undeploy the control plane services

```bash
cd ~/install_yamls
make openstack_deploy_cleanup   # removes service instances, keeps the operator
```

### Step 5: Delete the openstack namespace BEFORE the operator

**This ordering is mandatory.** `make openstack_cleanup` deletes the
openstack-operator first; the child StatefulSets it owned (galera, memcached,
nova-*, ceilometer, ...) are then orphaned and keep recreating their pods.
`make crc_storage_cleanup` then blocks forever on a PVC held by a pod that
can no longer be deleted (PVC stuck `Terminating`).

Use the upstream `namespace_cleanup` target — it deletes the keystone and
mariadb operators, removes the `openstack` project (and with it every child
StatefulSet/Pod/PVC), and cleans `out/openstack` so a redeploy regenerates
it. `NAMESPACE` defaults to `openstack`:

```bash
cd ~/install_yamls
make namespace_cleanup
# wait until it is actually gone before touching the operator/storage
until ! oc get project openstack &>/dev/null; do sleep 5; done
```

If it hangs, a service was still reconciling; check for a StatefulSet still
owning pods (`oc get sts -n openstack`) and re-run. Do **not** try to fix it
by force-deleting individual pods — the owner recreates them.

### Step 6: Optional — remove operator + storage PVs

Now safe, because nothing is referencing the PVs any more.

```bash
make openstack_cleanup          # OLM subscription/CSV/catalogsource
make crc_storage_cleanup        # the 100 local-storage PVs
```

`crc_storage_cleanup` is near-instant when the PVs were already released. If
it still hangs, the namespace was not fully removed — go back to Step 5. If
it exits non-zero, verify no PVs are left:
`oc get pv -l provisioned-by=crc-devsetup` should be empty.

### Step 7: Destroy CRC

```bash
cd ~/install_yamls/devsetup
make crc_cleanup                # deletes CRC VM, keeps bundle cache (fast redeploy)
# make crc_scrub                # also wipes ~/.crc and the crc binary
```

`make crc_cleanup` ends by running `make -C .. secrets_clean`, which prints
`error: Missing or incomplete configuration info` twice — harmless, the
kubeconfig is already gone by then. The target still exits 0.

### Step 8: Verify

```bash
virsh list --all                    # empty (needs qemu:///system, see above)
ls ~/install_yamls/.secrets.env     # gone

# NOTE: `crc status` prints "does not seem to be setup correctly" even on a
# SUCCESSFUL teardown — CRC keeps its cache. Do not rely on its wording;
# check for the actual VM artifacts instead:
ls ~/.crc/machines/crc/*.qcow2      # expect: no such file
virsh --connect qemu:///system list --name   # expect: no output
ls -d ~/install_yamls/out/openstack # expect: no such file (namespace_cleanup)
```

Drop the leftover DHCP reservation so the next `crc_attach_default_interface`
does not error (each deploy re-adds it, so this is safe to run even if you are
about to redeploy):

```bash
virsh --connect qemu:///system net-update default delete ip-dhcp-host \
  "<host mac='52:54:00:11:11:10' ip='192.168.122.10'/>" --config --live
```

Optional cleanup of the ~27 GB CRC bundle cache (skips the fast redeploy):

```bash
cd ~/install_yamls/devsetup && make crc_scrub
```

Expected wall-clock ~5-10 min measured end-to-end (namespace deletion and
CRC destroy dominate); a multi-node topology with large disks may take
longer.

Teardown gotchas:

- **Residue a "clean" teardown leaves behind.** Even when steps 1-8 pass,
  these survive and bite the next deployment: the libvirt `default` network
  keeps the DHCP reservation for `52:54:00:11:11:10` / `192.168.122.10`
  (causes `crc_attach_default_interface` to error on redeploy — see Step 4),
  a stale but inert `~/.kube/config` with `clusters: null` remains,
  `~/install_yamls/out/edpm/*.xml` keeps old node definitions, and `~/.crc`
  keeps the ~27 GB bundle cache. `make namespace_cleanup` (Step 5) removes
  `out/openstack`; the rest are harmless but worth knowing.
- **Step 5 ordering is the big one.** Running `openstack_cleanup` before
  deleting the `openstack` namespace orphans the service StatefulSets. The
  symptom is `crc_storage_cleanup` hanging on
  `oc delete pvc/mysql-db-openstack-galera-0` while `openstack-galera-0` is
  `Running` — and force-deleting the pod just makes the orphaned StatefulSet
  recreate it. Use `make namespace_cleanup`; do not chase individual pods.
- **Two mandatory env settings.** Without `eval $(crc oc-env)` the devsetup
  cleanup scripts call a nonexistent `oc` and fail *silently* (no non-zero
  exit), leaving stale agents and nova services. Without
  `VIRSH_DEFAULT_CONNECT_URI=qemu:///system`, `virsh list` reports an empty
  list even though CRC and the EDPM nodes are running — this makes a broken
  teardown look successful.
- **Never `pkill -f` cleanup scripts.** `crc_storage_cleanup` runs inside the
  same shell as the rest of the teardown; killing it lets the script proceed
  to `crc_cleanup`, which destroys CRC (and the `oc` endpoint) out from under
  any later step. Fix the ordering instead.
- **`edpm_deploy_cleanup` ignores networkers.** It only applies
  `out/openstack/dataplane/cr` (the compute nodeSet). The networker nodeSet
  lives in a separate `out/openstack/dataplane/networker_cr` and survives —
  delete `openstack-edpm-ipam-networker` explicitly (Step 1).
- **Node counts default to 1.** `devsetup/Makefile` sets
  `EDPM_TOTAL_NODES ?= 1` / `EDPM_TOTAL_NETWORKERS ?= 1`. Without the explicit
  counts in Step 2, cleanup removes only node `-0` and leaks the rest (both
  VM and qcow2).
- **The agent purge is in the wrong place upstream.** `edpm_deploy_cleanup` →
  `scripts/cleanup-edpm_deploy.sh` greps only `edpm-compute-` and runs before
  the VMs are destroyed, so live agents re-register and networkers are never
  matched. Step 3 is the fix.
- **`confirm-delete` annotation.** Deleting a deployment that is still
  running is rejected with "deletion of a running deployment not allowed".
  Set the annotation before `oc delete`.
- **NodeSets cannot be deleted while a deployment references them** — hence
  the deployment-first ordering.

## Troubleshooting

- **`oc: command not found` in make steps** — `eval $(crc oc-env)` was not run
  in that shell. It is required for every make that shells out to oc. Note the
  crc binary is at `~/bin/crc` (not `~/.crc/bin`), and `oc-env` reports the oc
  path as `~/.crc/bin/oc`. Affected targets include `edpm_compute` and
  `edpm_networker` (via `gen-ansibleee-ssh-key.sh`) — these fail with a bare
  `make: *** Error 127` rather than this message, because the missing `oc`
  call is inside a helper script.
- **catalog pods `ImagePullBackOff` in openshift-marketplace / `make openstack`
  stuck at `validate_marketplace`** — invalid `registry.redhat.io` credentials
  in the pull secret. Fix the file, then update the cluster secret and restart
  catalog pods (kubelet picks up the new secret within ~2-3 min):
  ```bash
  oc set data secret/pull-secret -n openshift-config --from-file=.dockerconfigjson=$HOME/pull-secret.txt
  oc delete pod -n openshift-marketplace --all
  ```
- **`make edpm_wait_deploy` times out after 30m** — normal with >= 3 nodes
  (full ansible run takes 35-45 min). The deployment continues in background;
  recover with:
  `oc wait openstackdataplanenodeset openstack-edpm-ipam -n openstack --for condition=Ready --timeout=40m`
  then run `make edpm_nova_discover_hosts`.
- **`edpm_deploy_networker`: "path out/operator/dataplane-operator/config/services
  does not exist"** — install_yamls bug (dataplane-operator merged into
  openstack-operator). Symlink workaround in Step 7.
- **`OpenStackDataPlaneDeployment Spec is immutable`** — delete and recreate
  the deployment CR with the full nodeSets list (Step 7).
- **`deletion of a running deployment not allowed`** — newer dataplane-operator
  webhooks reject deleting a deployment that has not finished. Set the
  annotation first:
  `oc annotate openstackdataplanedeployment edpm-deployment -n openstack dataplane.openstack.org/confirm-delete=true --overwrite`
  then `oc delete`. Same annotation is needed for the re-creation workaround
  above whenever the previous deployment is still running.
- **PlacementAPI "internal endpoint not found" during openstack_deploy** —
  transient while Keystone rolls out; re-check with `oc wait` as above.
- **`crc_storage_cleanup` hangs on a `mysql-db-*-galera-0` PVC, pod stuck
  `Running`** — `openstack_cleanup` ran before the `openstack` namespace was
  deleted, orphaning the service StatefulSets, which keep recreating the pod
  and holding the PVC in `Terminating`. Force-deleting the pod does not help
  (the StatefulSet recreates it). Fix: `oc delete namespace openstack
  --timeout=600s` and wait for it to disappear, *then* run the operator and
  storage cleanup. Do not `pkill` the cleanup script — the rest of the
  teardown continues and destroys CRC under you.
- **`virsh list --all` shows an empty list although VMs are running** — the
  domains live under `qemu:///system` (install_yamls runs virsh via sudo);
  a plain user session connects to `qemu:///session`. Always use
  `export VIRSH_DEFAULT_CONNECT_URI=qemu:///system` or
  `virsh --connect qemu:///system list --all`. Missing this makes a broken
  teardown look successful.
- **devsetup cleanup scripts fail silently** — `edpm_compute_cleanup` /
  `edpm_networker_cleanup` / `edpm-node-cleanup.sh` shell out to bare `oc`.
  If `eval $(crc oc-env)` was not run they print `oc: command not
  found` deep in the output, skip deleting the stale OVN chassis and nova
  services, and still exit 0.
- **ospng can't self-SSH from host** — not needed; install_yamls runs virsh
  via sudo and ansible via in-cluster EE pods.

## Environment facts

- OSCP name created by install_yamls: `openstack-galera-network-isolation`
- NodeSet names: `openstack-edpm-ipam` (computes),
  `openstack-edpm-ipam-networker` (networkers)
- EDPM IPs: computes 192.168.122.100+, networkers 192.168.122.200+
- Teardown: see the **Teardown** section above (ordered; the old one-line
  `make ..._cleanup` list left networker nodeSets and VMs behind)
