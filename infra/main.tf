# Provider configuration for AWS
provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = "centrico-livelab-mlops"
      ManagedBy = "terraform"
      Owner     = "nepryoon"
    }
  }
}

# Terraform backend configuration for remote state
terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket         = "nepryoon-mlops-tfstate"
    key            = "centrico-livelab-mlops/terraform.tfstate"
    region         = "eu-south-1"
    encrypt        = true
    dynamodb_table = "nepryoon-mlops-tfstate-lock"
  }
}

# Data source to get current AWS account ID
data "aws_caller_identity" "current" {}

# Data source to get available availability zones
data "aws_availability_zones" "available" {
  state = "available"
}

# Validate that we're operating in the correct AWS account
locals {
  expected_account_id = "102724112773"
  account_check       = data.aws_caller_identity.current.account_id == local.expected_account_id ? true : tobool("FATAL: Expected account ${local.expected_account_id}, got ${data.aws_caller_identity.current.account_id}")
}
