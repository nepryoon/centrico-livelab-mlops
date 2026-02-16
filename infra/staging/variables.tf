variable "aws_region" {
  type        = string
  description = "AWS region"
  default     = "eu-south-1"
}

variable "app_prefix" {
  type        = string
  description = "Prefix for resource names"
  default     = "centrico-livelab"
}

variable "environment" {
  type        = string
  description = "Environment name"
  default     = "stg"
}

variable "db_username" {
  type        = string
  description = "RDS master username"
  default     = "app"
}

variable "db_password" {
  type        = string
  description = "RDS master password (min 8 chars). Keep out of git."
  sensitive   = true

  validation {
    condition     = length(var.db_password) >= 8
    error_message = "db_password must be at least 8 characters."
  }
}

# ----------------------------
# LLM / Explain
# ----------------------------
variable "llm_enabled" {
  type        = bool
  description = "Enable LLM calls for /explain"
  default     = true
}

variable "openai_model" {
  type        = string
  description = "OpenAI model name used by /explain"
  default     = "gpt-4o-mini"
}

variable "openai_api_key_secret_arn" {
  type        = string
  description = "Secrets Manager ARN for OpenAI API key (valueFrom in ECS task)"
  default     = ""
}

variable "explain_token" {
  type        = string
  description = "If non-empty, /explain requires header X-Explain-Token"
  sensitive   = true
  default     = ""
}
