variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "eu-south-1"
}

variable "app_prefix" {
  description = "Prefix used for naming AWS resources"
  type        = string
  default     = "centrico-livelab"
}

variable "db_password" {
  description = "RDS master password (8-128 chars). Must not contain space, /, \", @."
  type        = string
  sensitive   = true

  validation {
    condition = (
      length(var.db_password) >= 8 &&
      length(var.db_password) <= 128 &&
      length(regexall("[/\"@\\s]", var.db_password)) == 0
    )
    error_message = "db_password must be 8-128 chars and must not contain space, /, \", @."
  }
}
