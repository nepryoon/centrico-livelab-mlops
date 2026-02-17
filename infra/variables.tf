# AWS Region
variable "aws_region" {
  type        = string
  description = "AWS region for all resources"
  default     = "eu-south-1"
}

# AWS Account ID
variable "aws_account_id" {
  type        = string
  description = "AWS account ID (used for validation)"
  default     = "102724112773"
}

# Application prefix for resource naming
variable "app_prefix" {
  type        = string
  description = "Prefix for resource names"
  default     = "nepryoon-mlops"
}

# VPC CIDR block
variable "vpc_cidr" {
  type        = string
  description = "CIDR block for VPC"
  default     = "10.0.0.0/16"
}

# ECS task configuration
variable "ecs_task_cpu" {
  type        = string
  description = "CPU units for ECS task"
  default     = "512"
}

variable "ecs_task_memory" {
  type        = string
  description = "Memory (MB) for ECS task"
  default     = "1024"
}

variable "ecs_desired_count" {
  type        = number
  description = "Desired number of ECS tasks"
  default     = 1
}

# Container port
variable "container_port" {
  type        = number
  description = "Port exposed by the container"
  default     = 8000
}

# GitHub repository for OIDC
variable "github_repo" {
  type        = string
  description = "GitHub repository for OIDC trust (format: owner/repo)"
  default     = "nepryoon/centrico-livelab-mlops"
}

# CloudWatch log retention
variable "log_retention_days" {
  type        = number
  description = "CloudWatch log retention in days"
  default     = 7
}

# CPU alarm threshold
variable "cpu_alarm_threshold" {
  type        = number
  description = "ECS CPU utilization alarm threshold (percentage)"
  default     = 80
}
