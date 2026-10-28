# devops-ai-kit

> Bản tiếng Anh là bản chuẩn; bản tiếng Việt có thể cập nhật chậm hơn. English: [README.md](README.md)

Bộ rules, skills, subagents và lớp bảo vệ giúp Claude Code làm việc DevOps / hạ tầng cloud an toàn và hữu ích hơn (Kubernetes, Terraform/OpenTofu, Ansible, Helm, Argo CD, Azure/AWS/GCP, on-prem).

Hướng dẫn đầy đủ: [docs/vi/huong-dan.md](docs/vi/huong-dan.md) · Thuật ngữ: [docs/en/glossary.md](docs/en/glossary.md) · Định danh cloud read-only: [docs/vi/cloud-readonly.md](docs/vi/cloud-readonly.md)

## Kit gồm những gì

| Lớp | Nội dung | Khi nào được nạp |
|---|---|---|
| Rules | `00-core` (an toàn, cấp rủi ro L0–L3, bằng chứng, tài liệu), `01-language` (ngôn ngữ đầu ra) + Terraform, Ansible, Kubernetes, Helm, Argo CD, Dockerfile, observability | `00-core` và `01-language` luôn nạp; các rule còn lại nạp qua `paths:` khi đụng tới file khớp |
| Skills | Quy trình `/infra-task`, `grill-me` (hỏi bạn cho tới khi đủ ngữ cảnh), `infra-docs` (change record, concept note, runbook, ADR, postmortem), 8 skill chuẩn thiết kế, 3 playbook (monitoring stack, migrate PostgreSQL bằng PGO, AKS) | Khi cần (khớp mô tả hoặc gọi bằng lệnh `/`) |
| Subagents | `infra-recon`, `infra-researcher`, `infra-reviewer`, `infra-verifier`, `infra-scribe` | Do `/infra-task` gọi, hoặc khi bạn yêu cầu |
| Lớp bảo vệ | Permission rules (deny/ask/allow), hook PreToolUse hiện đúng nơi tác động (context, namespace, workspace, subscription) trên mọi lệnh mutating, RBAC read-only + script tạo kubeconfig cho AI | Claude Code / Kubernetes cưỡng chế, không phụ thuộc model |

## Bắt đầu nhanh

```bash
git clone https://github.com/hoangminhung/devops-ai-kit.git ~/devops-ai-kit && cd ~/devops-ai-kit
./install.sh --dry-run --lang vi   # xem trước, không ghi gì
./install.sh --lang vi             # cài vào ~/.claude, tài liệu và báo cáo viết tiếng Việt
./check.sh                         # trạng thái, ngôn ngữ đầu ra, công cụ gate nào đã có
```

Sau đó mở phiên Claude Code mới và kiểm tra bằng `/context`, `/skills`, `/agents`, `/permissions`, `/hooks`.

`--lang` chọn ngôn ngữ cho tài liệu bàn giao và báo cáo của agents: `en` (mặc định) hoặc `vi`. README, PR description, commit message và code comment luôn viết tiếng Anh. Chat trả lời theo ngôn ngữ bạn đang dùng. Cài lại mà không có `--lang` thì giữ lựa chọn trước đó.

**Bước tiếp theo rất nên làm:** cho AI dùng kubeconfig read-only.

```bash
setup/k8s/make-ai-kubeconfig.sh --apply-rbac --readonly <prod-context> --passthrough <dev-context>
./install.sh --env KUBECONFIG=~/.kube/ai-config
```

Với CLI của cloud (Azure / AWS / GCP), xem [docs/vi/cloud-readonly.md](docs/vi/cloud-readonly.md).

## Dùng hằng ngày

- Việc L0/L1: prompt như bình thường; rules tự áp dụng.
- Chưa rõ nên yêu cầu gì, hoặc Claude thiếu ngữ cảnh: `/grill-me <chủ đề>`. Claude hỏi từng vòng ngắn, câu nào cũng kèm đáp án đề xuất.
- Project chạy lâu: giữ một file `PROGRESS.md` (mẫu trong `templates/`). Claude đọc nó đầu mỗi phiên và cập nhật sau mỗi việc, nên hết phiên cũng không mất gì.
- Việc L2/L3: `/infra-task <mô tả>` → recon → research → plan → review → **cổng duyệt** → implement → review → **cổng duyệt** → execute → verify → docs. Làm tiếp bất cứ lúc nào bằng `/infra-task resume <thư-mục-task>`.

## Cấu trúc thư mục

```
devops-ai-kit/
├── install.sh · uninstall.sh · check.sh
├── claude/                  # được cài vào ~/.claude/
│   ├── rules/devops-kit/    # 00-core + 7 rule theo công nghệ
│   ├── lang/                # en.md, vi.md → 01-language.md
│   ├── skills/              # 14 skill
│   ├── agents/              # 5 subagent
│   ├── hooks/devops-kit/    # infra-context-guard.py
│   └── settings.devops-kit.json
├── scripts/                 # kit.py (bộ cài), run-kit.sh, validate.py
├── setup/k8s/               # RBAC read-only + script tạo kubeconfig cho AI
├── templates/               # CLAUDE.md mẫu cho project, PROGRESS.md, .gitignore bổ sung
├── tests/                   # test cho hook và bộ cài
└── docs/{en,vi}/            # hướng dẫn, thuật ngữ, thiết lập cloud read-only
```

## Cập nhật / gỡ cài

Sửa file trong repo này (không sửa trong `~/.claude`), hoặc `git pull`, rồi chạy lại `./install.sh`. `./uninstall.sh` gỡ mọi thứ kit đã thêm, kể cả các dòng trong `settings.json`. Nếu bạn không sửa `settings.json` sau khi cài, file được trả về đúng từng byte như ban đầu.

## Kiểm tra khi phát triển

```bash
python3 scripts/validate.py                  # frontmatter, name, paths, độ dài, file tham chiếu, còn sót tiếng Việt
python3 -m unittest discover -s tests -v     # test hook + bộ cài (HOME tạm)
shellcheck -S warning *.sh scripts/*.sh setup/k8s/*.sh
```

CI (`.github/workflows/ci.yml`) chạy đúng các kiểm tra này trên mỗi push và pull request.

## Khác gì so với các kit khác

Trên GitHub đã có nhiều bộ skill DevOps cho Claude Code, và nhiều hook chặn lệnh `kubectl` / `terraform` nguy hiểm. Kit này không thay thế chúng. Điểm kit này thêm vào là sự kết hợp:

- quy trình thay đổi hạ tầng (`/infra-task`) có hai cổng duyệt của con người;
- các agent recon, review và verify chạy trong context riêng;
- thư mục task làm tiếp được qua nhiều phiên và nhiều máy;
- tài liệu bàn giao có đánh dấu bằng chứng (✅ đã kiểm chứng · 📖 theo tài liệu · ⚠️ suy luận);
- RBAC và kubeconfig read-only cho AI, để an toàn không chỉ dựa vào model;
- playbook cho Longhorn, migrate bằng Crunchy PGO và AKS;
- tài liệu tiếng Anh và tiếng Việt, có tùy chọn để AI viết đầu ra bằng tiếng Việt.

## Yêu cầu

Claude Code (bản gần đây), Python 3.8+, bash (trên Windows: Git Bash hoặc PowerShell). Công cụ gate không bắt buộc nhưng nên có: `kubeconform`, `tflint`, `trivy`, `ansible-lint`, `promtool`, `amtool`, `hadolint`, `infracost`, `helm-diff`. Chạy `./check.sh` để xem còn thiếu gì.

## Giấy phép

[MIT](LICENSE)
