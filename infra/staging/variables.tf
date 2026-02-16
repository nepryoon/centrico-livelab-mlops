variable "aws_region" {
  type        = string
  description = "AWS region"
}

variable "app_prefix" {
  type        = string
  description = "Resource name prefix"
  default     = "centrico-livelab"
}

variable "container_port" {
  type        = number
  default     = 8000
}

variable "db_name" {
  type        = string
  default     = "livelab"
}

variable "db_user" {
  type        = string
  default     = "app"
}

# Staging convenience. For production, use a stronger random secret + rotation.
variable "db_password" {
  type        = string
  default     = "app"
  sensitive   = true
}
