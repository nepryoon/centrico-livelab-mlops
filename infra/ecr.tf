# ECR Repository - Container registry for ML inference service Docker images
resource "aws_ecr_repository" "inference" {
  name                 = "${var.app_prefix}-inference"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name    = "${var.app_prefix}-inference"
    Service = "inference"
  }
}

# ECR Lifecycle Policy - Keep only the last 10 images to save storage costs
resource "aws_ecr_lifecycle_policy" "inference" {
  repository = aws_ecr_repository.inference.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 10 images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 10
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}
