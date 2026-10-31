output "config_file" {
  description = "Path of the generated config file."
  value       = local_file.config.filename
}

output "release_name" {
  description = "Random release name for this environment."
  value       = random_pet.release.id
}
