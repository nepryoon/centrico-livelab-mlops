output "tfstate_bucket" {
  value = aws_s3_bucket.tfstate.bucket
}

output "tflock_table" {
  value = aws_dynamodb_table.tflock.name
}

output "gha_role_arn" {
  value = aws_iam_role.gha_staging.arn
}
