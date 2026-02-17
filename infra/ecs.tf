# ECS Cluster - Container orchestration cluster for inference service
resource "aws_ecs_cluster" "main" {
  name = "${var.app_prefix}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = {
    Name = "${var.app_prefix}-cluster"
  }
}

# ECS Task Definition - Defines the inference service container configuration
resource "aws_ecs_task_definition" "inference" {
  family                   = "centrico-inference"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.ecs_task_cpu
  memory                   = var.ecs_task_memory

  execution_role_arn = aws_iam_role.ecs_task_execution.arn
  task_role_arn      = aws_iam_role.ecs_task_role.arn

  container_definitions = jsonencode([
    {
      name      = "inference"
      image     = "${aws_ecr_repository.inference.repository_url}:latest"
      essential = true

      portMappings = [
        {
          containerPort = var.container_port
          protocol      = "tcp"
        }
      ]

      # CloudWatch Logs configuration
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.ecs_inference.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
        }
      }

      # Environment variables from SSM Parameter Store
      secrets = [
        {
          name      = "DATABASE_URL"
          valueFrom = aws_ssm_parameter.database_url.arn
        }
      ]

      # Health check
      healthCheck = {
        command     = ["CMD-SHELL", "curl -f http://localhost:${var.container_port}/health || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 60
      }
    }
  ])

  tags = {
    Name    = "centrico-inference"
    Service = "inference"
  }
}

# ECS Service - Manages the running tasks behind the load balancer
resource "aws_ecs_service" "inference" {
  name            = "inference"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.inference.arn
  desired_count   = var.ecs_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets         = [aws_subnet.private_1.id, aws_subnet.private_2.id]
    security_groups = [aws_security_group.ecs.id]
    # Set to false since tasks are in private subnets with NAT Gateway
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.inference.arn
    container_name   = "inference"
    container_port   = var.container_port
  }

  # Ensure ALB listener is created before the service
  depends_on = [aws_lb_listener.http]

  tags = {
    Name    = "${var.app_prefix}-inference-service"
    Service = "inference"
  }
}
