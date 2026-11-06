# Image for approve-all benchmark runs (scenarios/isolation/run-in-container.sh).
# Network is used only while building; at run time the container's only exit is the egress proxy.
FROM ubuntu:24.04
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      git jq python3 make ca-certificates curl unzip \
 && rm -rf /var/lib/apt/lists/*
ARG TF_VERSION=1.14.7
RUN curl -fsSLo /tmp/tf.zip "https://releases.hashicorp.com/terraform/${TF_VERSION}/terraform_${TF_VERSION}_linux_amd64.zip" \
 && unzip -q /tmp/tf.zip terraform -d /usr/local/bin && rm /tmp/tf.zip
# Providers of sandbox/repo, served from a local mirror so `terraform init` needs no network.
COPY mirror.tf /opt/mirror/main.tf
RUN cd /opt/mirror && terraform providers mirror /opt/tf-mirror && rm -rf /opt/mirror
COPY terraformrc /etc/terraformrc
COPY egress_proxy.py /opt/egress_proxy.py
COPY approver.py /opt/approver.py
ENV TF_CLI_CONFIG_FILE=/etc/terraformrc \
    DISABLE_AUTOUPDATER=1 \
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
