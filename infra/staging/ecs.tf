resource "aws_cloudwatch_log_group" "inference" {
  name              = "/ecs/centrico-livelab/inference"
  retention_in_days = 14
}

resource "aws_ecs_cluster" "this" {
  name = "centrico-livelab-stg"
}

resource "aws_iam_role" "ecs_task_execution" {
  name = "centrico-livelab-ecs-task-exec-stg"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = "sts:AssumeRole"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "ecs_task_role" {
  name = "centrico-livelab-ecs-task-role-stg"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = "sts:AssumeRole"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
    }]
  })
}

# ✅ allow ECS task to read artifacts from S3
resource "aws_iam_policy" "ecs_task_s3_artifacts_read" {
  name = "centrico-livelab-ecs-task-s3-artifacts-read-stg"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ListBucket"
        Effect = "Allow"
        Action = ["s3:ListBucket"]
        Resource = aws_s3_bucket.artifacts.arn
      },
      {
        Sid    = "GetObjects"
        Effect = "Allow"
        Action = ["s3:GetObject"]
        Resource = "${aws_s3_bucket.artifacts.arn}/*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_task_s3_artifacts_read" {
  role       = aws_iam_role.ecs_task_role.name
  policy_arn = aws_iam_policy.ecs_task_s3_artifacts_read.arn
}

resource "aws_ecs_task_definition" "inference" {
  family                   = "centrico-livelab-inference"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
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
        { containerPort = 8000, hostPort = 8000, protocol = "tcp" }
      ]

      environment = [
        { name = "AWS_REGION", value = var.aws_region },
        { name = "PORT", value = "8000" },
        { name = "ARTIFACT_DIR", value = "/artifacts" },
        { name = "ARTIFACT_S3_URI", value = "s3://${aws_s3_bucket.artifacts.bucket}/models/latest/" }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.inference.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "ecs"
        }
      }
    }
  ])
}

# service + LB resources sono in networking.tf (target group / ALB / SG)
resource "aws_ecs_service" "inference" {
  name            = "inference"
  cluster         = aws_ecs_cluster.this.id
  launch_type     = "FARGATE"
  desired_count   = 1
  task_definition = aws_ecs_task_definition.inference.arn

  network_configuration {
    subnets          = data.aws_subnets.default.ids
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.inference.arn
    container_name   = "inference"
    container_port   = 8000
  }

  depends_on = [aws_lb_listener.http]
}
