# Password of the prod database user `web`. Created once by Terraform; the app gets it from
# the Kubernetes Secret in deploy/web/db-secret.yaml (kept in sync by hand, see docs).
resource "random_password" "db" {
  length  = 24
  special = false
}

output "db_password" {
  description = "Password of the prod database user web."
  value       = random_password.db.result
  sensitive   = true
}
