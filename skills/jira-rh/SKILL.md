---
name: jira-rh
description: Manages JIRA issues using Atlassian MCP. This skill is tailor made for the Red Hat RHOSO project.
---

# JIRA Management Skill

A comprehensive Claude Code skill for managing JIRA issues, projects, and workflows using the Atlassian MCP server.

## Table of Contents

- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [Skill Workflow](#skill-workflow)
  - [Issue Types](#1-issue-types)
  - [Issue hierarchy](#2-issue-hierarchy)
  - [Types of reports](#3-types-of-reports)
- [Best Practices](#best-practices)
- [Common Use Cases](#common-use-cases)
- [References](#references)
- [Troubleshooting](#troubleshooting)

## Overview

This skill provides JIRA management capabilities including:
- Jira ticket definition in RHOSO project.
- Inspecting and retrieving information from these tickets.
- Generating reports.

## Prerequisites

It is needed to configure the Jira MCP server in the Claude configuration. For example, under `~/.claude/settings.json`.

The configuration parameters are:
```json
{
...
  "mcpServers": {
    "jira_rh": {
      "type": "stdio",
      "command": "npx",
      "args": [
        "-y",
        "@sooperset/mcp-atlassian"
      ],
      "env": {
        "JIRA_URL": "https://issues.redhat.com",
        "JIRA_USERNAME": "<your Jira user>",
        "JIRA_API_TOKEN": "<your token for Claude>"
      }
    }
  }
...
}
```

The token can be created in `https://issues.redhat.com/secure/ViewProfile.jspa`, in the **Personal Access Tokens** section.

