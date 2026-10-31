module "app_config" {
  source      = "../../modules/app-config"
  environment = "prod"
  replicas    = var.replicas
  output_dir  = "${path.root}/../../../out"
}

resource "null_resource" "notify" {
  triggers = { release = module.app_config.release_name }
}
