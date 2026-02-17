# Terraform Infrastructure Guide - Centrico LiveLab MLOps

This directory contains the complete Terraform infrastructure-as-code for the Centrico LiveLab MLOps platform on AWS.

## Architecture Overview

The infrastructure provisions a production-ready MLOps pipeline with the following components:

- **VPC**: Custom VPC (10.0.0.0/16) with public and private subnets across 2 AZs
- **ECS Fargate**: Serverless container orchestration for the ML inference service
- **ALB**: Internet-facing Application Load Balancer for HTTP traffic
- **ECR**: Docker container registry with lifecycle policies
- **S3**: Versioned storage for ML model artifacts
- **IAM**: Least-privilege roles for ECS tasks and GitHub Actions OIDC
- **CloudWatch**: Centralized logging and CPU utilization alarms
- **SSM Parameter Store**: Secure storage for sensitive configuration

## Prerequisites

1. **Terraform**: Version >= 1.6.0
   ```bash
   terraform version
   ```

2. **AWS CLI**: Version 2.x
   ```bash
   aws --version
   ```

3. **AWS Credentials**: Configure credentials for AWS account `102724112773`
   ```bash
   aws configure
   # or use AWS SSO:
   aws sso login --profile nepryoon
   ```

4. **Verify AWS Access**:
   ```bash
   aws sts get-caller-identity
   # Should return Account: 102724112773
   ```

## Bootstrap: Remote State Backend (One-time Setup)

Before running Terraform for the first time, you need to manually create the S3 bucket and DynamoDB table for remote state management.

### Step 1: Create S3 Bucket for Terraform State

```bash
aws s3 mb s3://nepryoon-mlops-tfstate --region eu-south-1

# Enable versioning
aws s3api put-bucket-versioning \
  --bucket nepryoon-mlops-tfstate \
  --versioning-configuration Status=Enabled \
  --region eu-south-1

# Enable encryption
aws s3api put-bucket-encryption \
  --bucket nepryoon-mlops-tfstate \
  --server-side-encryption-configuration '{
    "Rules": [{
      "ApplyServerSideEncryptionByDefault": {
        "SSEAlgorithm": "AES256"
      }
    }]
  }' \
  --region eu-south-1

# Block public access
aws s3api put-public-access-block \
  --bucket nepryoon-mlops-tfstate \
  --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true \
  --region eu-south-1
```

### Step 2: Create DynamoDB Table for State Locking

```bash
aws dynamodb create-table \
  --table-name nepryoon-mlops-tfstate-lock \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region eu-south-1
```

### Step 3: Verify Bootstrap Resources

```bash
aws s3 ls s3://nepryoon-mlops-tfstate --region eu-south-1
aws dynamodb describe-table --table-name nepryoon-mlops-tfstate-lock --region eu-south-1
```

## Initial Deployment

### Step 1: Initialize Terraform

```bash
cd infra
terraform init
```

This will:
- Download the AWS provider
- Configure the remote S3 backend
- Initialize the DynamoDB state locking

### Step 2: Validate Configuration

```bash
terraform validate
```

### Step 3: Review the Execution Plan

```bash
terraform plan
```

Review the plan carefully. It should show approximately 40+ resources to be created.

### Step 4: Apply the Infrastructure

```bash
terraform apply
```

Type `yes` when prompted. The apply process takes approximately 5-10 minutes.

### Step 5: Save Outputs

After successful apply, save the important outputs:

```bash
terraform output > outputs.txt

# Key outputs:
terraform output alb_url                     # HTTP endpoint for your service
terraform output ecr_repository_url          # Push Docker images here
terraform output ecs_cluster_name            # ECS cluster name
terraform output ecs_service_name            # ECS service name
terraform output github_actions_role_arn     # Role ARN for GitHub Actions
```

## Post-Deployment Configuration

### 1. Update SSM Parameters

The SSM parameters are created with placeholder values. Update them with real values:

```bash
# Update DATABASE_URL (if using RDS)
aws ssm put-parameter \
  --name "/centrico/DATABASE_URL" \
  --value "postgresql://user:password@host:5432/dbname" \
  --type SecureString \
  --overwrite \
  --region eu-south-1

# Update OPENAI_API_KEY
aws ssm put-parameter \
  --name "/centrico/OPENAI_API_KEY" \
  --value "sk-..." \
  --type SecureString \
  --overwrite \
  --region eu-south-1
```

### 2. Build and Push Initial Docker Image

```bash
# Login to ECR
aws ecr get-login-password --region eu-south-1 | \
  docker login --username AWS --password-stdin \
  $(terraform output -raw ecr_repository_url)

# Build your inference service Docker image
docker build -t nepryoon-mlops-inference:latest ./services/inference

# Tag for ECR
docker tag nepryoon-mlops-inference:latest \
  $(terraform output -raw ecr_repository_url):latest

# Push to ECR
docker push $(terraform output -raw ecr_repository_url):latest
```

### 3. Force ECS Service Deployment

After pushing the first image, force a new deployment:

```bash
aws ecs update-service \
  --cluster $(terraform output -raw ecs_cluster_name) \
  --service $(terraform output -raw ecs_service_name) \
  --force-new-deployment \
  --region eu-south-1
```

### 4. Verify Service is Running

```bash
# Check service status
aws ecs describe-services \
  --cluster $(terraform output -raw ecs_cluster_name) \
  --services $(terraform output -raw ecs_service_name) \
  --region eu-south-1

# Test the endpoint
curl $(terraform output -raw alb_url)/health
```

### 5. Subscribe to SNS Alerts (Optional)

```bash
# Subscribe your email to CloudWatch alarms
aws sns subscribe \
  --topic-arn $(terraform output -raw sns_topic_arn) \
  --protocol email \
  --notification-endpoint your-email@example.com \
  --region eu-south-1

# Confirm the subscription via the email you receive
```

## Updating the Infrastructure

### Modify Infrastructure

1. Edit the relevant `.tf` files
2. Run `terraform plan` to preview changes
3. Run `terraform apply` to apply changes

```bash
terraform plan
terraform apply
```

### Update ECS Service After New Docker Image

When you push a new Docker image to ECR with the `latest` tag:

```bash
# Option 1: Force new deployment (uses existing task definition)
aws ecs update-service \
  --cluster $(terraform output -raw ecs_cluster_name) \
  --service $(terraform output -raw ecs_service_name) \
  --force-new-deployment \
  --region eu-south-1

# Option 2: Update task definition and deploy (if you've changed task config)
terraform apply
```

### Rolling Back

If you need to rollback to a previous task definition:

```bash
# List task definitions
aws ecs list-task-definitions --family-prefix centrico-inference

# Update service to use a specific revision
aws ecs update-service \
  --cluster $(terraform output -raw ecs_cluster_name) \
  --service $(terraform output -raw ecs_service_name) \
  --task-definition centrico-inference:REVISION_NUMBER \
  --region eu-south-1
```

## GitHub Actions Integration

The infrastructure creates an IAM role for GitHub Actions using OIDC (no long-lived credentials).

### Configure GitHub Secrets

Add the following secrets to your GitHub repository (Settings → Secrets and variables → Actions):

1. **AWS_REGION**: `eu-south-1`
2. **AWS_ACCOUNT_ID**: `102724112773`
3. **AWS_ROLE_ARN**: (value from `terraform output github_actions_role_arn`)

### Example GitHub Actions Workflow

```yaml
name: Deploy to AWS

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    permissions:
      id-token: write
      contents: read
    
    steps:
      - uses: actions/checkout@v3
      
      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_ROLE_ARN }}
          aws-region: ${{ secrets.AWS_REGION }}
      
      - name: Login to Amazon ECR
        id: login-ecr
        uses: aws-actions/amazon-ecr-login@v2
      
      - name: Build and push Docker image
        env:
          ECR_REGISTRY: ${{ steps.login-ecr.outputs.registry }}
          ECR_REPOSITORY: nepryoon-mlops-inference
          IMAGE_TAG: ${{ github.sha }}
        run: |
          docker build -t $ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG .
          docker push $ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG
          docker tag $ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG $ECR_REGISTRY/$ECR_REPOSITORY:latest
          docker push $ECR_REGISTRY/$ECR_REPOSITORY:latest
      
      - name: Deploy to ECS
        run: |
          aws ecs update-service \
            --cluster nepryoon-mlops-cluster \
            --service inference \
            --force-new-deployment
```

## Monitoring and Troubleshooting

### View CloudWatch Logs

```bash
# Stream logs in real-time
aws logs tail /ecs/centrico-inference --follow --region eu-south-1

# View logs from the last hour
aws logs tail /ecs/centrico-inference --since 1h --region eu-south-1
```

### Check ECS Service Health

```bash
# Service status
aws ecs describe-services \
  --cluster $(terraform output -raw ecs_cluster_name) \
  --services $(terraform output -raw ecs_service_name) \
  --region eu-south-1 \
  --query 'services[0].{Status:status,Running:runningCount,Desired:desiredCount,Events:events[0:3]}'

# List running tasks
aws ecs list-tasks \
  --cluster $(terraform output -raw ecs_cluster_name) \
  --service-name $(terraform output -raw ecs_service_name) \
  --region eu-south-1
```

### Common Issues

**Issue**: ECS tasks keep stopping
- Check CloudWatch logs for errors
- Verify SSM parameters are set correctly
- Ensure Docker image has correct health check endpoint

**Issue**: ALB health checks failing
- Verify the container exposes port 8000
- Ensure `/health` endpoint returns HTTP 200
- Check security group rules allow ALB → ECS traffic

**Issue**: Cannot pull ECR image
- Verify image exists: `aws ecr describe-images --repository-name nepryoon-mlops-inference`
- Check ECS task execution role has ECR permissions

## Cost Optimization

Estimated monthly costs (us-east-1 pricing, may vary by region):

- **VPC**: NAT Gateway ~$32/month
- **ECS Fargate**: 0.5 vCPU + 1GB RAM ~$15/month (24/7)
- **ALB**: ~$16/month + data transfer
- **S3**: ~$1/month (assuming <100GB storage)
- **CloudWatch Logs**: ~$0.50/month (7-day retention)
- **DynamoDB**: Pay-per-request (minimal cost)

**Total**: ~$65-75/month

### Cost Savings Tips

1. **Reduce ECS task count**: Set `ecs_desired_count = 0` when not in use
2. **Use scheduling**: Start/stop ECS service on a schedule
3. **Optimize NAT Gateway**: Consider using VPC endpoints for S3/ECR instead

## Destroying the Infrastructure

⚠️ **Warning**: This will permanently delete all resources. Ensure you have backups of important data.

```bash
# Preview what will be destroyed
terraform plan -destroy

# Destroy all resources
terraform destroy
```

After destruction, you may want to manually delete:
- ECR images (not deleted by default)
- S3 bucket contents (if versioning is enabled)
- CloudWatch log groups (if retention is set)

## File Structure

```
infra/
├── main.tf            # Provider, backend, data sources, account validation
├── variables.tf       # Input variables with defaults
├── outputs.tf         # Output values (URLs, ARNs, names)
├── vpc.tf             # VPC, subnets, IGW, NAT, route tables, security groups
├── ecr.tf             # ECR repository with lifecycle policy
├── s3.tf              # S3 artifacts bucket with encryption and versioning
├── iam.tf             # IAM roles and policies (ECS, GitHub Actions)
├── ecs.tf             # ECS cluster, task definition, service
├── alb.tf             # Application Load Balancer, target group, listener
├── ssm.tf             # SSM Parameter Store for secrets
├── cloudwatch.tf      # Log groups, alarms, SNS topic
├── terraform.tfvars   # Variable values for this environment
└── README_TERRAFORM.md # This file
```

## Additional Resources

- [Terraform AWS Provider Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs)
- [AWS ECS Best Practices](https://docs.aws.amazon.com/AmazonECS/latest/bestpracticesguide/intro.html)
- [GitHub Actions OIDC with AWS](https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/configuring-openid-connect-in-amazon-web-services)

## Support

For issues or questions:
1. Check CloudWatch Logs for application errors
2. Review Terraform plan output before applying changes
3. Consult AWS documentation for service-specific issues
4. Open an issue in the GitHub repository

---

**Last Updated**: 2024-02-17  
**Terraform Version**: >= 1.6  
**AWS Provider Version**: ~> 5.0
