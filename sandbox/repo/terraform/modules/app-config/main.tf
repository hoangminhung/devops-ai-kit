resource "random_pet" "release" {
  keepers = { environment = var.environment }
}

resource "local_file" "config" {
  filename = "${var.output_dir}/${var.environment}.json"
  content = jsonencode({
    environment = var.environment
    replicas    = var.replicas
    release     = random_pet.release.id
  })
}
