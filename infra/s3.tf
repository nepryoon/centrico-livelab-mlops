# S3 Bucket - Storage for versioned ML model artifacts
resource "aws_s3_bucket" "artifacts" {
  bucket = "${var.app_prefix}-artifacts"

  tags = {
    Name    = "${var.app_prefix}-artifacts"
    Purpose = "ML model artifacts storage"
  }
}

# Enable versioning - Track all versions of model artifacts
resource "aws_s3_bucket_versioning" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  versioning_configuration {
    status = "Enabled"
  }
}

# Server-side encryption - Encrypt all objects with AES256
resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Block all public access - Ensure artifacts are never publicly accessible
resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
