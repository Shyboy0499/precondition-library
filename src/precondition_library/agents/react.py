"""Arm 1: the ReAct baseline. No library, full LLM cost per episode.

This arm is the honest yardstick the other two are measured against, so it must
be given every advantage a reasonable engineer would give it by hand: a good
system prompt, the same tool surface the compiled programs get, and the same
sandbox. A deliberately crippled baseline would make the other arms look better
and the result worthless.

The stopping rule is the part a later reader is most likely to "simplify" back
into a defect, so it is stated on `solve` as well as here: the loop stops when
the model declares the task finished, or when `max_steps` runs out. It must
**not** stop when the ground-truth checker says the environment is good. Issue
#9 names that as the flaw in an earlier sketch of this arm: a checker used as a
stopping oracle hands arm 1 information the compiled arms do not have (they run
a body once and are graded afterwards), so the baseline's success would be a
property of the oracle rather than of the agent. Nothing here imports ground
truth; the caller grades the returned transcript with the fault's own `check`.
"""

from __future__ import annotations

import json
import shlex
import subprocess

from ..program import EpisodeOutcome
from ..provider import Provider
from ..sandbox import Sandbox, run_git
from ..signatures import TaskSignature

_GIT_TIMEOUT_S = 30.0
"""Wall-clock bound on one tool call. A git command in a local sandbox is
instant; anything slower is a hang, and hanging unattended is a failure mode."""

_MAX_OUTPUT_CHARS = 4_000
"""Per-stream cap on what is fed back, so one noisy command cannot balloon the
transcript that every later turn re-sends (and is billed for)."""

_SHELL_OPERATORS = {"&&", "||", ";", "|", "&", ">", ">>", "<", "`"}
"""Refused because the tool runs one git command with no shell: these tokens
would otherwise reach git as literal arguments and produce a confusing error."""

_REPO_RETARGETING = ("-C", "--git-dir", "--work-tree")
"""git options that point the command at a repository other than `env.work`."""

_FINISH_WORDS = {"done", "finish", "finished", "submit", "complete", "completed"}

SYSTEM_PROMPT = """\
You are a git maintenance agent working in a single disposable repository. You
complete the user's request by running git commands and reading their output.

You have exactly one tool, `run_git`, which runs one git command in the
repository's working directory. There is no file-reader, no shell, and no other
tool.

Reply with one JSON object per turn, optionally after a sentence of reasoning:
- To run a command:
  {"tool": "run_git", "arguments": {"command": "git status --porcelain"}}
  The command must start with `git`. Shell operators (&&, |, ;, redirects) and
  options that retarget the repository are refused; issue one command per turn.
- To declare the task finished:
  {"done": true}

After each command you receive its exit code, stdout and stderr. Read failures
and correct them. Preserve anything the user told you must survive, and do not
declare the task finished until you believe the request is satisfied."""

_NO_ACTION_NUDGE = (
    "No action was recognised. Reply with one JSON object: either "
    '{"tool": "run_git", "arguments": {"command": "<git command>"}} to act, '
    'or {"done": true} to finish.'
)


def solve(
    signature: TaskSignature,
    env: Sandbox,
    provider: Provider,
    *,
    max_steps: int = 12,
) -> tuple[EpisodeOutcome, list[dict]]:
    """Run the arm-1 loop and return its outcome with the full transcript.

    The loop sends the system prompt and the task text, lets the model call the
    one tool, feeds each result back, and repeats. It ends when the model
    declares the task finished or after `max_steps` model turns, whichever comes
    first.

    **The stopping rule must not consult the fault's checker.** A ground-truth
    oracle here would give arm 1 information the compiled arms are never given:
    they execute a body once and are graded afterwards, with no opportunity to
    loop until the environment passes. Stopping on the model's own declaration
    keeps the mechanism identical to a hand-run ReAct agent, and keeps the
    measurement attributable to the agent rather than to the oracle. Do not
    replace `_parse_action`-driven termination with `fault.check(env).ok`; the
    caller grades the result with that checker after this function returns.

    Outcome mapping. Arm 1 is the fallback path itself -- there is no stored
    program and no dispatch -- so `EpisodeOutcome.SUCCESS`, which would assert
    the episode was correct, is never returned here. A model that declares
    itself finished completes its attempt and yields `FALLBACK` (spec §8: "no
    program applies" is expected, not a failure); exhausting the step budget or
    a provider error yields `FAIL`, with the reason left in the transcript.
    Correctness is separate and is the caller's `ground_truth_ok`.

    The transcript is a first-class output, not a debugging aid: the compile
    step reads it to author a program, so it records the system prompt, the task
    text, every model turn (with the parsed tool call when there is one), and
    every tool result, in order.
    """
    task_text = signature.intent
    transcript: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task_text},
    ]
    tools = available_tools()

    for _ in range(max_steps):
        try:
            completion = provider.complete(
                system=SYSTEM_PROMPT, messages=_api_messages(transcript), tools=tools
            )
        except Exception as exc:  # provider errors are recorded, never swallowed
            transcript.append(
                {"role": "error", "content": f"provider error: {type(exc).__name__}: {exc}"}
            )
            return EpisodeOutcome.FAIL, transcript

        text = completion.text
        action = _parse_action(text)

        if action is None:
            transcript.append({"role": "assistant", "content": text})
            transcript.append({"role": "user", "content": _NO_ACTION_NUDGE})
            continue

        kind, value = action
        if kind == "finish":
            transcript.append({"role": "assistant", "content": text, "done": True})
            return EpisodeOutcome.FALLBACK, transcript

        if kind == "unknown":
            result, ok = _refused(f"unknown tool {value!r}; only 'run_git' exists"), False
            transcript.append(
                {
                    "role": "assistant",
                    "content": text,
                    "tool_call": {"name": value, "arguments": {}},
                }
            )
            transcript.append({"role": "tool", "name": value, "content": result, "ok": ok})
            continue

        result, ok = _run_tool(value, env)
        transcript.append(
            {
                "role": "assistant",
                "content": text,
                "tool_call": {"name": "run_git", "arguments": {"command": value}},
            }
        )
        transcript.append(
            {"role": "tool", "name": "run_git", "command": value, "content": result, "ok": ok}
        )

    transcript.append(
        {
            "role": "error",
            "content": (
                f"step budget exhausted after {max_steps} steps without a finish declaration"
            ),
        }
    )
    return EpisodeOutcome.FAIL, transcript


def available_tools() -> list[dict]:
    """The one tool every arm gets, in the OpenAI/DeepSeek function-calling shape.

    Identical across arms so the tool surface cannot explain a difference
    between them. The schema is sent to the provider; the loop reads back the
    text protocol the system prompt pins, because `Completion` carries text only
    (`provider.py` sends `tools` but does not surface a structured `tool_calls`
    field).

    What contains the tool's risk
    -----------------------------
    The **sandbox** is the containment: `env.work` is a disposable clone built
    by `sandbox.create`, destroyed after the episode, and never a real fork. The
    checks in `_run_tool` -- argv[0] must be `git`, no shell operators, no
    option that retargets the repository -- keep the command pointed at that
    clone; they are not a security boundary against a determined model, because
    a git command can still damage the sandbox. Damaging the sandbox is the
    accepted cost; damaging the host is not, and running without a shell is what
    makes `rm -rf ...` a refusal rather than an execution.

    This is deliberately **not** `runtime.guard`. The guard constrains a
    replayed program body that runs unattended and may contain arbitrary shell;
    it is stricter than this and is issue #10's territory. Nothing here
    implements it.
    """
    tools: list[dict] = [
        {
            "type": "function",
            "function": {
                "name": "run_git",
                "description": (
                    "Run one git command in the sandbox working directory and return its "
                    "exit code, stdout and stderr. The command must start with 'git'."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "One git command line, e.g. 'git status --porcelain'.",
                        }
                    },
                    "required": ["command"],
                },
            },
        }
    ]
    return tools


def _run_tool(command: str, env: Sandbox) -> tuple[str, bool]:
    """Run one model-supplied command; return (result text, ok).

    Refusals and git failures are returned as text rather than raised, so the
    model can read them and correct itself in the next turn. See
    `available_tools` for what this guard is and is not.
    """
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return _refused(f"could not parse command {command!r}: {exc}"), False
    if not argv:
        return _refused("empty command"), False
    if argv[0] != "git":
        return _refused(f"only git commands are allowed, got {argv[0]!r}"), False
    if any(token in _SHELL_OPERATORS for token in argv[1:]):
        return _refused("one git command per call; shell operators are not run"), False
    retargeting = [token for token in argv[1:] if token.startswith(_REPO_RETARGETING)]
    if retargeting:
        return (
            _refused(f"{retargeting[0]!r} would run outside the sandbox working directory"),
            False,
        )

    try:
        result = run_git(argv[1:], cwd=env.work, check=False, timeout=_GIT_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return f"timed out after {_GIT_TIMEOUT_S:.0f}s", False
    return _format_output(result), result.returncode == 0


def _refused(reason: str) -> str:
    return f"refused: {reason}"


def _format_output(result: subprocess.CompletedProcess[str]) -> str:
    parts = [f"exit code: {result.returncode}"]
    if result.stdout.strip():
        parts.append(f"stdout:\n{_truncate(result.stdout)}")
    if result.stderr.strip():
        parts.append(f"stderr:\n{_truncate(result.stderr)}")
    return "\n".join(parts)


def _truncate(text: str) -> str:
    if len(text) <= _MAX_OUTPUT_CHARS:
        return text
    return text[:_MAX_OUTPUT_CHARS] + f"\n[truncated; {len(text)} characters total]"


def _api_messages(transcript: list[dict]) -> list[dict]:
    """Map the transcript onto the message roles the provider protocol accepts.

    The system prompt is passed separately and errors are terminal, so both are
    dropped here; a tool result becomes a `user` message because the text
    protocol has no `tool_call_id` to answer (the provider does not surface one).
    """
    messages: list[dict] = []
    for entry in transcript:
        role = entry["role"]
        if role in ("system", "error"):
            continue
        if role == "tool":
            command = entry.get("command")
            label = f"tool result for git command {command!r}" if command else "tool result"
            messages.append({"role": "user", "content": f"{label}:\n{entry['content']}"})
        else:
            messages.append({"role": role, "content": entry["content"]})
    return messages


def _parse_action(text: str) -> tuple[str, str] | None:
    """Read the model's turn as ("finish", ""), ("tool", command), ("unknown", name).

    Returns None when no JSON object is present or the object carries no action,
    which the loop answers with a nudge rather than a crash. The protocol is
    text-based because `Completion` carries only text; `available_tools` and the
    system prompt define the encoding.
    """
    obj = _extract_json_object(text)
    if obj is None:
        return None
    if any(obj.get(key) is True for key in ("done", "finished", "finish")):
        return "finish", ""
    action = obj.get("action")
    if isinstance(action, str) and action.lower() in _FINISH_WORDS:
        return "finish", ""
    name = obj.get("tool") or obj.get("name")
    if name is None and isinstance(action, str):
        name = action
    arguments = obj.get("arguments")
    if arguments is None:
        arguments = obj.get("args")
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except ValueError:
            arguments = {"command": arguments}
    command = arguments.get("command") if isinstance(arguments, dict) else None
    if not isinstance(command, str):
        command = obj.get("command") if isinstance(obj.get("command"), str) else None
    if name is not None and name not in ("run_git", "run"):
        return "unknown", str(name)
    if command is None:
        return None
    return "tool", command


def _extract_json_object(text: str) -> dict | None:
    """The first JSON object in `text`, tolerating prose and code fences.

    Models wrap their action in explanation or a ```json fence; a baseline that
    could not read that would be crippled by formatting rather than reasoning.
    Scanning for a balanced object means one stray brace in prose does not
    discard an otherwise valid action.
    """
    direct = _try_load(text.strip())
    if direct is not None:
        return direct
    for start, character in enumerate(text):
        if character != "{":
            continue
        end = _matching_brace(text, start)
        if end is None:
            continue
        parsed = _try_load(text[start : end + 1])
        if parsed is not None:
            return parsed
    return None


def _matching_brace(text: str, start: int) -> int | None:
    """Index of the `}` closing the `{` at `start`, ignoring braces in strings."""
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        character = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return index
    return None


def _try_load(text: str) -> dict | None:
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None
