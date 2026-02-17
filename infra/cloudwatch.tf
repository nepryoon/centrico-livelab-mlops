# CloudWatch Log Group - Centralized logging for ECS inference service
resource "aws_cloudwatch_log_group" "ecs_inference" {
  name              = "/ecs/centrico-inference"
  retention_in_days = var.log_retention_days

  tags = {
    Name    = "/ecs/centrico-inference"
    Service = "inference"
  }
}

# SNS Topic - Alert notifications for CloudWatch alarms
resource "aws_sns_topic" "alerts" {
  name = "${var.app_prefix}-alerts"

  tags = {
    Name = "${var.app_prefix}-alerts"
  }
}

# CloudWatch Metric Alarm - ECS CPU utilization > 80%
resource "aws_cloudwatch_metric_alarm" "ecs_cpu_high" {
  alarm_name          = "${var.app_prefix}-ecs-cpu-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "CPUUtilization"
  namespace           = "AWS/ECS"
  period              = 300
  statistic           = "Average"
  threshold           = var.cpu_alarm_threshold
  alarm_description   = "Alert when ECS service CPU exceeds ${var.cpu_alarm_threshold}%"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  dimensions = {
    ClusterName = aws_ecs_cluster.main.name
    ServiceName = aws_ecs_service.inference.name
  }

  tags = {
    Name    = "${var.app_prefix}-ecs-cpu-high"
    Service = "inference"
  }
}
