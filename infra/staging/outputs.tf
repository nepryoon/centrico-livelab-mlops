output "alb_url" {
  value = "http://${aws_lb.app.dns_name}"
}

output "db_endpoint" {
  value = aws_db_instance.postgres.address
}

output "ecr_repo_url_inference" {
  value = aws_ecr_repository.inference.repository_url
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.this.name
}

output "ecs_service_name" {
  value = aws_ecs_service.inference.name
}

output "artifacts_bucket" {
  value = aws_s3_bucket.artifacts.bucket
}

output "artifacts_s3_uri_latest" {
  value = "s3://${aws_s3_bucket.artifacts.bucket}/models/latest/"
}
