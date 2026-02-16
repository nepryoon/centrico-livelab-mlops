# Centrico LiveLab — AWS Staging Starter (ECS Fargate + ALB)

This is a **starter kit** to deploy the *inference* service to AWS **ECS Fargate** behind an **ALB**, using **Terraform** + **GitHub Actions (OIDC, no long-lived keys)**.

Default assumptions (edit if needed):
- AWS Account: `102724112773`
- Region: `eu-west-1`
- GitHub repo: `nepryoon/centrico-livelab-mlops`
- GitHub Environment: `staging`

## 0) Prereqs
- Terraform >= 1.6
- AWS CLI configured locally (for the **first** `terraform apply`)

## 1) Bootstrap (one-time): tfstate backend + GitHub OIDC role
```bash
cd infra/bootstrap
terraform init
terraform apply -auto-approve \
  -var aws_region=eu-west-1 \
  -var github_repo=nepryoon/centrico-livelab-mlops
```

Outputs:
- `tfstate_bucket` = `centrico-livelab-tfstate-102724112773`
- `tflock_table` = `centrico-livelab-tflock`
- `gha_role_arn` (use this in GitHub Actions)

## 2) Staging infra: ALB + ECS + RDS + ECR
```bash
cd ../staging
terraform init \
  -backend-config="bucket=centrico-livelab-tfstate-102724112773" \
  -backend-config="key=staging/terraform.tfstate" \
  -backend-config="region=eu-west-1" \
  -backend-config="dynamodb_table=centrico-livelab-tflock" \
  -backend-config="encrypt=true"

terraform apply -auto-approve -var aws_region=eu-west-1
```

After apply, note the outputs:
- `alb_url` (public endpoint)
- `ecs_cluster_name`, `ecs_service_name`
- `ecr_repo_url_inference`
- `db_endpoint`
- `artifacts_bucket` (S3 bucket for model artifacts)
- `artifacts_s3_uri_latest` (S3 URI for latest model version)

## 3) Model Artifacts Auto-load
The ECS inference service automatically loads model artifacts from S3 on container startup:
- **S3 Location**: `s3://{artifacts_bucket}/models/latest/`
- **Container Path**: `/artifacts`
- **Mechanism**: The `entrypoint.sh` script runs `aws s3 sync` before starting the API server
- **Permissions**: ECS task role has `s3:GetObject` and `s3:ListBucket` permissions

To publish a new model:
```bash
# Upload artifacts to S3
aws s3 sync ./artifacts s3://{artifacts_bucket}/models/latest/ --delete

# Trigger ECS service redeployment
aws ecs update-service \
  --cluster {ecs_cluster_name} \
  --service {ecs_service_name} \
  --force-new-deployment
```

Or use the GitHub Actions workflow: `.github/workflows/train-publish-staging.yml`

## 4) GitHub Actions CD (build/push + deploy)
Copy `.github/workflows/cd-staging.yml` into your repo.

Then, in GitHub:
- Settings → Environments → create `staging`
- (optional but recommended) add protection rules for `main`

The workflow assumes the role created in Bootstrap via OIDC.

## Notes / hardening
- This starter uses **default VPC/subnets** for speed.
  For production: create a dedicated VPC with private subnets + NAT.
- RDS is created for staging convenience; consider sizing/cost controls.

