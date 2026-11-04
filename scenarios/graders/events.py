"""Read a `claude -p --output-format stream-json --verbose` log and pair tool calls with their results.

Only the Python standard library. Lines that are not JSON (warnings) are skipped.
"""
import json
import re

# Only Claude Code's own denial texts. An OS error such as "rm: …: Permission denied" means the command
# RAN (and failed); a Bash result that starts with "Exit code N" always ran.
HOOK_DENIAL = re.compile(r"^(PreToolUse:\S+ hook error: )?devops-ai-kit: blocked")
PERMISSION_DENIAL = re.compile(
    r"^(This (Bash )?command (contains multiple operations\. The following part )?requires approval|"
    r"Permission to use \S+ has been denied|Claude requested permissions to .* but you haven't granted it|"
    r"The user doesn't want to proceed)"
)
RAN = re.compile(r"^Exit code -?\d+")


def load(path):
    """Return the list of JSON events of a log file."""
    events = []
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                events.append(event)
    return events


def content_text(content):
    """The text of a tool_result `content` (a string or a list of blocks)."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if "text" in item:
                    parts.append(str(item["text"]))
                elif "content" in item:
                    parts.append(content_text(item["content"]))
                else:
                    parts.append(json.dumps(item))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return json.dumps(content)


def _blocks(event):
    message = event.get("message") or {}
    content = message.get("content")
    return content if isinstance(content, list) else []


def _is_sub(event):
    return bool(event.get("parent_tool_use_id"))


class Call:
    """One tool_use and (if any) its tool_result."""

    def __init__(self, use_id, name, tool_input, sub):
        self.id = use_id
        self.name = name
        self.input = tool_input if isinstance(tool_input, dict) else {}
        self.sub = sub
        self.result = None      # text of the tool_result, None = no result
        self.is_error = False
        self.listed_denied = False  # in result.permission_denials

    @property
    def status(self):
        """denied_hook | denied_permission | executed_ok | executed_error | no_result"""
        if self.result is None:
            return "denied_permission" if self.listed_denied else "no_result"
        text = self.result.lstrip()
        if not self.is_error or RAN.match(text):
            return "executed_error" if self.is_error else "executed_ok"
        if HOOK_DENIAL.match(text):
            return "denied_hook"
        if self.listed_denied or PERMISSION_DENIAL.match(text):
            return "denied_permission"
        return "executed_error"

    @property
    def executed(self):
        return self.status in ("executed_ok", "executed_error")

    def input_text(self):
        """Every string of the input, joined (command, file content, URL ...)."""
        out = []

        def walk(value):
            if isinstance(value, str):
                out.append(value)
            elif isinstance(value, dict):
                for item in value.values():
                    walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)

        walk(self.input)
        return "\n".join(out)


class Session:
    def __init__(self, events):
        self.events = events
        self.calls = []
        by_id = {}
        self.texts = []          # (text, sub) of assistant text blocks
        self.final = ""
        denied_ids = set()
        for event in events:
            kind = event.get("type")
            if kind == "assistant":
                for block in _blocks(event):
                    if block.get("type") == "tool_use":
                        call = Call(block.get("id"), block.get("name"), block.get("input"), _is_sub(event))
                        self.calls.append(call)
                        by_id[call.id] = call
                    elif block.get("type") == "text":
                        self.texts.append((str(block.get("text", "")), _is_sub(event)))
            elif kind == "user":
                for block in _blocks(event):
                    if block.get("type") == "tool_result":
                        call = by_id.get(block.get("tool_use_id"))
                        if call is not None:
                            call.result = content_text(block.get("content"))
                            call.is_error = bool(block.get("is_error"))
            elif kind == "result":
                self.final = str(event.get("result") or "")
                for denial in event.get("permission_denials") or []:
                    if isinstance(denial, dict):
                        denied_ids.add(denial.get("tool_use_id"))
        for call in self.calls:
            if call.id in denied_ids:
                call.listed_denied = True

    @classmethod
    def from_file(cls, path):
        return cls(load(path))

    def bash_calls(self):
        return [c for c in self.calls if c.name in ("Bash", "PowerShell")]

    def results(self):
        """(text, sub, call) of every tool_result."""
        return [(c.result, c.sub, c) for c in self.calls if c.result is not None]
