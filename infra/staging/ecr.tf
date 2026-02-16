resource "aws_ecr_repository" "inference" {
  name = "${var.app_prefix}-inference"
  image_scanning_configuration {
    scan_on_push = true
  }
}
