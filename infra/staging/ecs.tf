locals {
  name_prefix = "${var.app_prefix}-${var.environment}"

  openai_secrets = var.openai_api_key_secret_arn != "" ? [
    {
      name      = "OPENAI_API_KEY"
      valueFrom = var.openai_api_key_secret_arn
    }
  ] : []

  explain_env = var.explain_token != "" ? [
    {
      name  = "EXPLAIN_TOKEN"
      value = var.explain_token
    }
  ] : []
}

resource "aws_cloudwatch_log_group" "inference" {
  name              = "/ecs/${var.app_prefix}/inference"
  retention_in_days = 14
}

resource "aws_ecs_cluster" "this" {
  name = local.name_prefix
}

resource "aws_iam_role" "ecs_task_execution" {
  name = "${var.app_prefix}-ecs-task-exec-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = "sts:AssumeRole"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Allow ECS execution role to read OpenAI secret (if configured)
resource "aws_iam_policy" "ecs_task_secrets_read" {
  name = "${var.app_prefix}-ecs-exec-secrets-read-${var.environment}"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat(
      var.openai_api_key_secret_arn != "" ? [
        {
          Sid      = "ReadOpenAISecret"
          Effect   = "Allow"
          Action   = ["secretsmanager:GetSecretValue"]
          Resource = var.openai_api_key_secret_arn
        }
      ] : [],
      [
        {
          Sid    = "KmsDecryptViaSecretsManager"
          Effect = "Allow"
          Action = ["kms:Decrypt"]
          Resource = "*"
          Condition = {
            StringEquals = {
              "kms:ViaService" = "secretsmanager.${var.aws_region}.amazonaws.com"
            }
          }
        }
      ]
    )
  })
}

resource "aws_iam_role_policy_attachment" "ecs_task_secrets_read" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = aws_iam_policy.ecs_task_secrets_read.arn
}

resource "aws_iam_role" "ecs_task_role" {
  name = "${var.app_prefix}-ecs-task-role-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = "sts:AssumeRole"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
    }]
  })
}

# Allow ECS task role to read artifacts from S3
resource "aws_iam_policy" "ecs_task_s3_artifacts_read" {
  name = "${var.app_prefix}-ecs-task-s3-artifacts-read-${var.environment}"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ReadArtifactsFromS3"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.artifacts.arn,
          "${aws_s3_bucket.artifacts.arn}/*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_task_s3_artifacts_read" {
  role       = aws_iam_role.ecs_task_role.name
  policy_arn = aws_iam_policy.ecs_task_s3_artifacts_read.arn
}

resource "aws_ecs_task_definition" "inference" {
  family                   = "${var.app_prefix}-inference"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"

  execution_role_arn = aws_iam_role.ecs_task_execution.arn
  task_role_arn      = aws_iam_role.ecs_task_role.arn

  container_definitions = jsonencode([
    {
      name      = "inference"
      image     = "${aws_ecr_repository.inference.repository_url}:bootstrap"
      essential = true

      portMappings = [
        {
          containerPort = 8000
          protocol      = "tcp"
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.inference.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "ecs"
        }
      }

      environment = concat(
        [
          { name = "ARTIFACT_DIR", value = "/artifacts" },
          { name = "ARTIFACT_S3_URI", value = "s3://${aws_s3_bucket.artifacts.bucket}/models/latest/" },

          # DB
          { name = "POSTGRES_HOST", value = aws_db_instance.postgres.address },
          { name = "POSTGRES_PORT", value = "5432" },
          { name = "POSTGRES_DB", value = "livelab" },
          { name = "POSTGRES_USER", value = var.db_username },
          { name = "POSTGRES_PASSWORD", value = var.db_password },

          # LLM toggles
          { name = "LLM_ENABLED", value = tostring(var.llm_enabled) },
          { name = "OPENAI_MODEL", value = var.openai_model }
        ],
        local.explain_env
      )

      secrets = local.openai_secrets
    }
  ])
}

resource "aws_ecs_service" "inference" {
  name            = "inference"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.inference.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    assign_public_ip = true
    subnets          = data.aws_subnets.default.ids
    security_groups  = [aws_security_group.ecs_tasks.id]
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.inference.arn
    container_name   = "inference"
    container_port   = 8000
  }

  depends_on = [aws_lb_listener.http]
}
