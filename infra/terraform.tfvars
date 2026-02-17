# AWS Configuration
aws_region     = "eu-south-1"
aws_account_id = "102724112773"

# Application Configuration
app_prefix = "nepryoon-mlops"

# VPC Configuration
vpc_cidr = "10.0.0.0/16"

# ECS Configuration
ecs_task_cpu      = "512"
ecs_task_memory   = "1024"
ecs_desired_count = 1
container_port    = 8000

# GitHub Configuration
github_repo = "nepryoon/centrico-livelab-mlops"

# Monitoring Configuration
log_retention_days  = 7
cpu_alarm_threshold = 80
