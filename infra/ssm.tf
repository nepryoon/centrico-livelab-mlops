# SSM Parameter - Placeholder for DATABASE_URL (to be populated manually or via automation)
resource "aws_ssm_parameter" "database_url" {
  name        = "/centrico/DATABASE_URL"
  description = "PostgreSQL connection string for the inference service"
  type        = "SecureString"
  value       = "placeholder_update_after_apply"

  tags = {
    Name    = "/centrico/DATABASE_URL"
    Service = "inference"
  }

  lifecycle {
    ignore_changes = [value]
  }
}

# SSM Parameter - Placeholder for OPENAI_API_KEY (to be populated manually)
resource "aws_ssm_parameter" "openai_api_key" {
  name        = "/centrico/OPENAI_API_KEY"
  description = "OpenAI API key for LLM-powered features"
  type        = "SecureString"
  value       = "placeholder_update_after_apply"

  tags = {
    Name    = "/centrico/OPENAI_API_KEY"
    Service = "inference"
  }

  lifecycle {
    ignore_changes = [value]
  }
}
