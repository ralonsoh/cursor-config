---
name: rhoso-debug
description: >-
  Access, debug, and test code on a RHOSO 18.0 testing environment deployed
  on baremetal. Use when the user asks to connect to a RHOSO environment,
  debug OpenStack on OpenShift, inspect OCP cluster nodes, check OpenStack
  operators or services, patch the OpenStackControlPlane, test code in
  RHOSO, mount code into an OpenStack pod, create an NFS share for a
  service, or mentions RHOSO, RHOSO 18, baremetal cluster, or OCP OpenStack.
---

# RHOSO 18.0 Environment Operations

Single entry point for operating a Red Hat OpenStack Services on OpenShift
(RHOSO) 18.0 testing environment deployed on a baremetal node.

Determine what the user needs, then read **only** the matching subskill:

- **Access, inspect, or debug the environment** (SSH to the cluster,
  `oc login`, inspect pods/operators/OSCP status, patch the OSCP CR) →
  Read [rhoso-access/SKILL.md](rhoso-access/SKILL.md)
- **Test local code changes live in a service pod** (NFS share, PV/PVC,
  extraMounts) →
  Read [rhoso-code/SKILL.md](rhoso-code/SKILL.md)

Subskills may be run in sequence: code testing requires environment
access first (rhoso-access), and rhoso-code says so in its prerequisites.
