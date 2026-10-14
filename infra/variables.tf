variable "region" {
  type    = string
  default = "us-east-1"
}

variable "prefix" {
  description = "Name prefix for every resource"
  type        = string
  default     = "llmgw"
}

variable "ssm_prefix" {
  description = "SSM path holding the secrets you created with scripts/put_secrets.sh"
  type        = string
  default     = "/llm-gateway"
}

variable "allowed_origin" {
  description = "CORS origin for the public dashboard routes (e.g. https://<user>.github.io)"
  type        = string
  default     = "*"
}
