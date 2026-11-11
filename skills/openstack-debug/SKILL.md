---
name: openstack-debug
description: >-
  Debug OpenStack environments by symptom. Currently covers DevStack
  deployment failures on remote VMs. Use when the user asks to debug a
  stack.sh/unstack.sh failure, a service that did not start, a hung
  devstack phase, or mentions DevStack problems on a remote-vm machine.
---

# OpenStack Debug

Single entry point for debugging OpenStack environments. Determine what the
user needs, then read **only** the matching subskill:

- **DevStack stack/unstack failures** (stack.sh hangs or dies, a service
  did not start, placement/cinder/keystone/glance init failures, tempest
  setup errors, re-stack weirdness after interrupted runs) →
  Read [devstack/SKILL.md](devstack/SKILL.md)

New subskills are added here as new debugging domains are collected
(e.g. OVS/OVN, control-plane services, CI jobs).
