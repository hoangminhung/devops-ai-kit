variable "environment" {
  type        = string
  description = "Environment name (dev or prod)."
  validation {
    condition     = contains(["dev", "prod"], var.environment)
    error_message = "environment must be dev or prod."
  }
}

variable "replicas" {
  type        = number
  description = "Number of web replicas written to the config file."
}

variable "output_dir" {
  type        = string
  description = "Folder where the config file is written."
}
