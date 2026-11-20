---
name: remote-host-config
description: >-
  Create a Linux bridge on a remote host and attach a NIC, and inspect an
  existing bridge, its ports, and forwarding. Use when the user asks to
  create a bridge, add a NIC to a bridge, check which device a bridge is
  built on, or see why a guest behind a bridge cannot reach the host LAN.
  Asks for the bridge name and the NIC when they are not given.
---

# Remote Host Configuration

Host network changes on a machine from the remote-vm inventory. Run every
command through [remote-vm-access](../remote-vm-access/SKILL.md).

## Required inputs

Before creating or modifying a bridge, the bridge name and the NIC must be
known. If the user did not give either one, ask. Do not invent names.

- Bridge name (for example `br_vms`)
- NIC to attach (for example `enp3s0`)
- Target host, when it is not already clear

## Inspect before changing

```bash
ip -br addr
ip route
nmcli -f DEVICE,TYPE,STATE,CONNECTION device status
nmcli -g GENERAL.CONNECTION device show <nic>
ip -d link show dev <nic>
ip link show type bridge
```

Record which device holds the host address and the default route. That
device is the management path.

**The NIC already carries the host address or the default route.** Stop.
Tell the user that attaching it drops SSH unless that address moves onto
the bridge. Do that only after the user confirms. See "Move the host
address onto the bridge" below.

**Another NIC holds the host address, and this NIC has no IPv4.** Safe to
attach. Leave the management NIC alone. Create the bridge with IPv4 and
IPv6 disabled. The bridge does not need an address for guests to reach the
LAN; bridging is layer 2.

A bridge port keeps no address of its own. An address that must survive
belongs on the bridge device.

Attach only one NIC from a given L2 network. A second NIC on that same LAN
loops the switch.

## Create the bridge and attach the NIC

Use NetworkManager so the change persists. Turn STP off. With STP on, a
new port stays in listening/learning for `forward_delay * 2` (about 30s)
and looks as if it is not forwarding.

`<nic-connection>` is the name from `GENERAL.CONNECTION`, which may differ
from the interface name. Quote it when it contains spaces.

```bash
nmcli connection add type bridge ifname <bridge> con-name <bridge> \
    bridge.stp no ipv4.method disabled ipv6.method disabled
nmcli connection modify "<nic-connection>" \
    connection.master <bridge> connection.slave-type bridge
nmcli connection up <bridge>
nmcli connection up "<nic-connection>"
```

When the NIC has no connection yet:

```bash
nmcli connection add type ethernet ifname <nic> con-name <nic> \
    master <bridge> slave-type bridge
nmcli connection up <nic>
```

When NetworkManager is not running, the same topology is:

```bash
sudo ip link add name <bridge> type bridge stp_state 0
sudo ip link set <bridge> up
sudo ip link set <nic> master <bridge>
```

That form does not survive reboot. Prefer NetworkManager when it manages
the NIC.

## Move the host address onto the bridge

Only after the user confirms, and only when the chosen NIC is the
management NIC. Read the current address, gateway, and DNS from that
connection first (`nmcli connection show "<nic-connection>"`). SSH drops
until the bridge is up.

```bash
nmcli connection modify <bridge> \
    ipv4.method manual ipv4.addresses <addr>/<prefix> \
    ipv4.gateway <gateway> ipv6.method disabled
nmcli connection modify "<nic-connection>" \
    connection.master <bridge> connection.slave-type bridge \
    ipv4.method disabled ipv6.method disabled
nmcli connection up <bridge>
nmcli connection up "<nic-connection>"
```

Copy `ipv4.dns` onto the bridge when the old connection had DNS servers.

## Verify

```bash
ip -d link show dev <bridge>
bridge link show master <bridge>
ip -br addr show dev <bridge>
ip -br addr show dev <nic>
nmcli -f NAME,TYPE,DEVICE connection show --active
```

Expect the bridge `state UP`, `stp_state 0`, and the NIC listed as
`master <bridge> state forwarding`. The NIC has no IPv4 of its own. The
management address is still on the other NIC, or on the bridge when the
user asked to move it.

`ip -br addr` accepts one device per invocation.

## Check a bridge and the device it is built on

The device under the bridge is its port: the NIC or tap enslaved to it.

```bash
ip -d link show type bridge
ip -d link show dev <bridge>
bridge link show master <bridge>
ls -l /sys/class/net/<bridge>/brif
ip -d link show master <bridge>
```

`bridge link` prints each port, its master, and its state (`forwarding`,
`listening`, `disabled`). `ip -d link show master <bridge>` adds the port
type (`bridge_slave`, and `tun type tap` for a VM tap). An empty `brif`
directory means the bridge has no uplink and guest frames stay on it.

Forwarding database and VLANs:

```bash
bridge fdb show br <bridge>
bridge vlan show
```

Addresses and which device owns the LAN route:

```bash
ip -br addr show dev <bridge>
ip route
nmcli connection show <bridge>
```

A tap port (`vnet*`) belongs to a libvirt guest. Match it with:

```bash
sudo virsh list --all
sudo virsh domiflist <domain>
ip -d link show dev <tap>
```

The guest MAC in `domiflist` matches the address learned on that tap
(`bridge fdb show br <bridge>`).

To see whether guest traffic reaches the LAN, capture on the tap and on
the uplink port:

```bash
sudo timeout 5 tcpdump -ni <tap> -e arp -c 10
sudo timeout 5 tcpdump -ni <nic> -e arp -c 10
```

ARP from the guest on the tap, and the same frames absent from the NIC,
means the NIC is not a port of this bridge or it is not on that LAN.
Confirm the NIC sees the LAN by capturing there before attaching it:
gateway ARP for `192.168.1.0/24` (or whichever subnet the guest uses)
shows the NIC is on that segment.
