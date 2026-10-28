# Định danh read-only cho phiên AI trên cloud

> Bản tiếng Anh (bản chuẩn): [../en/cloud-readonly.md](../en/cloud-readonly.md)

Mục tiêu giống như phía Kubernetes: phiên Claude Code dùng một định danh **chỉ đọc**. Mọi lệnh thay đổi trên cloud do bạn tự chạy, hoặc đi qua pipeline / PR.

Cách làm chung cho cả ba cloud:

1. Tạo định danh có quyền đọc.
2. Đăng nhập định danh đó vào một **thư mục cấu hình riêng** của CLI.
3. Trỏ Claude Code tới thư mục đó bằng biến môi trường trong `settings.json`.

Phiên terminal bình thường của bạn không bị ảnh hưởng. Cú pháp CLI có thể thay đổi theo version, nên kiểm tra `--help` của bản đang cài.

## Azure

**1. Tạo service principal có role Reader** (chạy bằng tài khoản của bạn):

```bash
az ad sp create-for-rbac --name claude-readonly \
  --role Reader --scopes /subscriptions/<subscription-id> \
  --create-cert
# Lưu lại appId, tenant và đường dẫn file cert (PEM chứa private key) mà lệnh in ra.
# Chuyển file PEM vào thư mục riêng, chmod 600.
```

**Reader làm được và không làm được gì:**

- Đọc được metadata tài nguyên.
- Không đọc được secret trong Key Vault (cần role data-plane riêng).
- Không lấy được access key của Storage Account.
- Không chạy được `az aks get-credentials`.

Muốn AI đọc thêm thứ gì, cấp role cụ thể ở scope hẹp, đừng nâng lên Contributor.

**2. Đăng nhập vào thư mục cấu hình riêng:**

```bash
export AZURE_CONFIG_DIR=~/.azure-ai
az login --service-principal --username <appId> --tenant <tenant-id> --certificate ~/.azure-ai-cert/claude-readonly.pem
# az CLI bản cũ dùng: --password <đường-dẫn-pem> thay cho --certificate
az account show --query "{name:name,id:id}"
unset AZURE_CONFIG_DIR
```

**Nếu máy chủ trung gian là VM trên Azure:** dùng user-assigned managed identity có role Reader, rồi `AZURE_CONFIG_DIR=~/.azure-ai az login --identity --client-id <client-id>`. Cách này không có file bí mật nào trên đĩa.

**3. Trỏ Claude Code tới thư mục này:**

```bash
cd ~/devops-ai-kit && ./install.sh --env AZURE_CONFIG_DIR=~/.azure-ai
```

## AWS

1. Tạo IAM role hoặc permission set (IAM Identity Center) gắn policy **`ViewOnlyAccess`**. Policy này chỉ xem metadata. Không dùng `ReadOnlyAccess`, vì nó cho phép đọc **nội dung** S3 object và nhiều loại dữ liệu khác.
2. Tạo profile `ai-readonly` trong `~/.aws/config` (SSO hoặc assume role).
3. Trỏ Claude Code tới profile đó: `./install.sh --env AWS_PROFILE=ai-readonly`.

## GCP

1. Tạo service account với role chỉ xem phù hợp (`roles/viewer` ở mức project, hoặc các role `*.viewer` cụ thể nếu muốn hẹp hơn). Ưu tiên impersonation thay cho tải key JSON.
2. Dùng thư mục cấu hình riêng: `CLOUDSDK_CONFIG=~/.config/gcloud-ai gcloud auth login ...` (hoặc cấu hình impersonation trong config đó).
3. Trỏ Claude Code tới đó: `./install.sh --env CLOUDSDK_CONFIG=~/.config/gcloud-ai`.

## Kiểm tra

Trong một phiên Claude mới, nhờ Claude chạy lệnh xem tài khoản (`az account show` / `aws sts get-caller-identity` / `gcloud config list`). Kết quả phải là định danh read-only, không phải tài khoản của bạn.
