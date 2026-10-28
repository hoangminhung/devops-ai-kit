# AWS

<!-- Last reviewed: 2026-10-28 -->

## Baseline
- **MUST** Terraform state on S3 with `use_lockfile = true` (DynamoDB locking is deprecated). The bucket has versioning, block public access and encryption turned on.
- **MUST** CI uses OIDC federation to an IAM role. People use IAM Identity Center (SSO). Do not create IAM users with long-lived access keys.
- **MUST** EC2 requires IMDSv2.
- **SHOULD** Gateway VPC Endpoints for S3 and DynamoDB (free) instead of going through the NAT Gateway.
- **SHOULD** Do not give instances / nodes a public IP. Outbound traffic goes through NAT.
- **SHOULD** Budget + Cost Anomaly Detection.

## Production
- **SHOULD** Workloads are spread over at least 2 AZs.
- **SHOULD** Interface VPC Endpoints (PrivateLink) for AWS services called often from private subnets (ECR, STS, Secrets Manager…). Compare the cost of each endpoint with the NAT cost.
- **SHOULD** EBS / S3 / RDS encryption on by default. KMS CMKs are **CONTEXT** (compliance, need to control the key policy).
- **SHOULD** GuardDuty, Security Hub, AWS Config turned on in the regions you use.
- **EKS:**
  - **MUST** Pods access AWS through EKS Pod Identity or IRSA. Do not attach permissions to the node instance role.
  - **CONTEXT** Karpenter instead of Cluster Autoscaler when the cluster has varied scaling needs.
  - **CONTEXT** Spot + Graviton (ARM64) for stateless workloads already built for multiple architectures. Infrastructure node pools use On-Demand.

## Enterprise landing zone
- AWS Organizations + Control Tower. Separate accounts by environment / workload. SCPs block dangerous actions.
- Hub-and-spoke network through Transit Gateway. Central egress control (AWS Network Firewall) when required.
- Central logging (CloudTrail organization trail) into a separate log account.
