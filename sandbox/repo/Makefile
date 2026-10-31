# Usage: make <target> e=<dev|prod>
e ?= dev
TF := terraform -chdir=terraform/envs/$(e)

.PHONY: init plan apply ansible-check
init:
	$(TF) init -input=false
plan: init
	$(TF) plan -input=false
apply: init
	$(TF) apply -input=false
ansible-check:
	cd ansible && ansible-playbook -i inventories/$(e)/hosts.ini playbooks/site.yml --check --diff
