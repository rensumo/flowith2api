import json
import re
from typing import Optional

TOOL_SYSTEM_PROMPT = """You have access to the following functions. Use them if required:

{tools_xml}

If a function should be called, respond in XML:
<function_calls>
<invoke name="function_name">
<parameter name="param1">value1</parameter>
</invoke>
</function_calls>

If no function is needed, respond normally."""


def build_tools_xml(tools: list) -> str:
    """Convert OpenAI tools format to XML description."""
    parts = []
    for t in tools:
        fn = t.get("function", t)
        name = fn.get("name", "")
        desc = fn.get("description", "")
        params = fn.get("parameters", {}) or {}
        props = params.get("properties", {})
        required = params.get("required", [])

        xml = f"  <tool name=\"{name}\" description=\"{desc}\">"
        if props:
            xml += "\n    <parameters>"
            for pname, pinfo in props.items():
                req = " required=\"true\"" if pname in required else ""
                ptype = pinfo.get("type", "string")
                pdesc = pinfo.get("description", "")
                xml += f"\n      <parameter name=\"{pname}\" type=\"{ptype}\"{req}>{pdesc}</parameter>"
            xml += "\n    </parameters>"
        xml += "\n  </tool>"
        parts.append(xml)

    return "\n".join(parts)


TOOL_CALL_RE = re.compile(
    r"<function_calls>\s*"
    r"(.*?)"
    r"\s*</function_calls>",
    re.DOTALL,
)

INVOKE_RE = re.compile(
    r"<invoke name=\"(.*?)\">\s*(.*?)\s*</invoke>", re.DOTALL
)

PARAM_RE = re.compile(r"<parameter name=\"(.*?)\">(.*?)</parameter>", re.DOTALL)


def parse_tool_calls(text: str) -> tuple[list[dict], str]:
    """Parse XML tool calls from response text.
    Returns (tool_calls, remaining_text)."""
    calls = []
    remaining = text

    for fc_match in TOOL_CALL_RE.finditer(text):
        fc_xml = fc_match.group(1)
        remaining = text[: fc_match.start()] + text[fc_match.end():]

        for inv_match in INVOKE_RE.finditer(fc_xml):
            name = inv_match.group(1)
            params_xml = inv_match.group(2)
            params = {}
            for p in PARAM_RE.finditer(params_xml):
                params[p.group(1)] = p.group(2)

            calls.append({
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(params, ensure_ascii=False),
                },
            })

    return calls, remaining


def prepare_messages_with_tools(messages: list, tools: Optional[list]) -> list:
    """Prepare messages by injecting tool definitions if tools are provided."""
    if not tools:
        return messages

    tools_xml = build_tools_xml(tools)
    sys_prompt = TOOL_SYSTEM_PROMPT.format(tools_xml=tools_xml)

    # Check if there's already a system message
    for i, m in enumerate(messages):
        if m.get("role") == "system":
            messages[i] = {"role": "system", "content": m["content"] + "\n\n" + sys_prompt}
            return messages

    return [{"role": "system", "content": sys_prompt}] + messages
