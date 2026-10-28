# Read-only cloud identity for AI sessions

> Vietnamese version: [../vi/cloud-readonly.md](../vi/cloud-readonly.md)

The goal is the same as on the Kubernetes side: the Claude Code session uses a **read-only** identity. You run every cloud change yourself, or it goes through a pipeline / PR.

The same approach works for all three clouds:

1. Create an identity that can only read.
2. Log that identity in to a **separate config folder** of the CLI.
3. Point Claude Code to that folder with an environment variable in `settings.json`.

Your normal terminal session is not affected. CLI syntax can change between versions, so check `--help` of the version you have installed.

## Azure

**1. Create a service principal with the Reader role** (run it with your own account):

```bash
az ad sp create-for-rbac --name claude-readonly \
  --role Reader --scopes /subscriptions/<subscription-id> \
  --create-cert
# Save the appId, tenant and the cert file path (a PEM with the private key) that the command prints.
# Move the PEM file to a private folder, chmod 600.
```

**What Reader can and cannot do:**

- It can read resource metadata.
- It cannot read secrets in Key Vault (that needs a separate data-plane role).
- It cannot get Storage Account access keys.
- It cannot run `az aks get-credentials`.

If you want the AI to read more, give a specific role at a narrow scope. Do not upgrade it to Contributor.

**2. Log in to the separate config folder:**

```bash
export AZURE_CONFIG_DIR=~/.azure-ai
az login --service-principal --username <appId> --tenant <tenant-id> --certificate ~/.azure-ai-cert/claude-readonly.pem
# Older az CLI versions use: --password <path-to-pem> instead of --certificate
az account show --query "{name:name,id:id}"
unset AZURE_CONFIG_DIR
```

**If your jump host is an Azure VM:** use a user-assigned managed identity with the Reader role, then `AZURE_CONFIG_DIR=~/.azure-ai az login --identity --client-id <client-id>`. With this method there is no secret file on disk.

**3. Point Claude Code to this folder:**

```bash
cd ~/devops-ai-kit && ./install.sh --env AZURE_CONFIG_DIR=~/.azure-ai
```

## AWS

1. Create an IAM role or a permission set (IAM Identity Center) with the **`ViewOnlyAccess`** policy. This policy only shows metadata. Do not use `ReadOnlyAccess`, because it allows reading the **content** of S3 objects and many other kinds of data.
2. Create an `ai-readonly` profile in `~/.aws/config` (SSO or assume role).
3. Point Claude Code to that profile: `./install.sh --env AWS_PROFILE=ai-readonly`.

## GCP

1. Create a service account with a suitable view-only role (`roles/viewer` at project level, or specific `*.viewer` roles if you want it narrower). Prefer impersonation over downloading a JSON key.
2. Use a separate config folder: `CLOUDSDK_CONFIG=~/.config/gcloud-ai gcloud auth login ...` (or set up impersonation in that config).
3. Point Claude Code to it: `./install.sh --env CLOUDSDK_CONFIG=~/.config/gcloud-ai`.

## Check

In a new Claude session, ask Claude to run a command that shows the account (`az account show` / `aws sts get-caller-identity` / `gcloud config list`). The result must be the read-only identity, not your own account.
