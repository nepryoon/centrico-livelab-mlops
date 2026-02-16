data "aws_caller_identity" "current" {}

locals {
  prefix         = "centrico-livelab"
  tfstate_bucket = "centrico-livelab-tfstate-102724112773"
  tflock_table   = "centrico-livelab-tflock"
  role_name      = "centrico-mlops-gha-staging"
}

# --- Remote state backend resources (S3 + DynamoDB lock) ---
resource "aws_s3_bucket" "tfstate" {
  bucket = local.tfstate_bucket
}

resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_dynamodb_table" "tflock" {
  name         = local.tflock_table
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"
  attribute {
    name = "LockID"
    type = "S"
  }
}

# --- GitHub OIDC provider ---
resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
  # AWS requires a thumbprint; GitHub's is commonly set to this value
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

# --- IAM role for GitHub Actions (OIDC) scoped to Environment=staging ---
resource "aws_iam_role" "gha_staging" {
  name = local.role_name

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Effect = "Allow",
      Principal = {
        Federated = aws_iam_openid_connect_provider.github.arn
      },
      Action = "sts:AssumeRoleWithWebIdentity",
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com",
          # Using GitHub Environments is the safest scoping
          "token.actions.githubusercontent.com:sub" = "repo:${var.github_repo}:environment:staging"
        }
      }
    }]
  })
}

# --- Minimal policy for CD: ECR push + ECS deploy (+ PassRole to ECS roles) ---
data "aws_iam_policy_document" "gha_cd" {
  statement {
    sid       = "ECRAuth"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid    = "ECRPushPull"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:CompleteLayerUpload",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
      "ecr:DescribeRepositories"
    ]
    resources = ["arn:aws:ecr:*:${data.aws_caller_identity.current.account_id}:repository/${local.prefix}-*"]
  }

  statement {
    sid    = "ECSDeploy"
    effect = "Allow"
    actions = [
      "ecs:DescribeServices",
      "ecs:DescribeTaskDefinition",
      "ecs:RegisterTaskDefinition",
      "ecs:UpdateService",
      "ecs:ListTasks",
      "ecs:DescribeTasks"
    ]
    resources = ["*"]
  }

  statement {
    sid     = "PassRoleToECS"
    effect  = "Allow"
    actions = ["iam:PassRole"]
    resources = [
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.prefix}-ecs-task-exec-*",
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.prefix}-ecs-task-role-*"
    ]
  }
}

resource "aws_iam_policy" "gha_cd" {
  name   = "${local.prefix}-gha-cd-staging"
  policy = data.aws_iam_policy_document.gha_cd.json
}

resource "aws_iam_role_policy_attachment" "gha_cd" {
  role       = aws_iam_role.gha_staging.name
  policy_arn = aws_iam_policy.gha_cd.arn
}
