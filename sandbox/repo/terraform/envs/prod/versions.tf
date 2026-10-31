terraform {
  required_version = "~> 1.14"
  required_providers {
    local  = { source = "hashicorp/local", version = "~> 2.5" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
    null   = { source = "hashicorp/null", version = "~> 3.2" }
  }
  backend "local" {
    path = "terraform.tfstate"
  }
}
