# Copyright 2025 OpenAI / Copyright 2025 Google LLC
# SPDX-License-Identifier: Apache-2.0
# Ported from openai/codex codex-rs/tui/assets/prompt_for_init_command.md + tui/src/chatwidget/slash_dispatch.rs
#   (SlashCommand::Init) (Apache-2.0), modified; grafted from google-gemini/gemini-cli
#   packages/core/src/commands/init.ts + packages/cli/src/ui/commands/initCommand.ts (Apache-2.0), modified.
"""输入框里的 `/init`：让助手看一遍工作区，写一份 AGENTS.md（项目说明 + 怎么跑 + 规矩），以后每轮自动遵守
（读取规则在 workspace_instructions.py）。这是 /init 的唯一规则。

三家比较（docs/core-research.md）：Codex = 把一段固定提示词当用户消息发出去（提示词里让模型自己先查“已存在就别动”）；
Gemini = 先在本地查 GEMINI.md，已有就直接回一句“没改动”、不调模型，没有才建空文件再发提示词，提示词还分“代码 / 非代码目录”；
deepseek-harness 没有。排名 ① Codex（提示词短、要求具体：200–400 字、标题、命令示例）② Gemini（存在检查放在模型外面，省钱、可靠）。
结论：用 Codex 的提示词做底，嫁接 Gemini 的“模型外先查”+“非代码目录”分支。
我们的改动：
- 存库的用户消息就是 `/init`（气泡上好看）；给模型时才换成提示词（render），而且只有“当前这一问”换成全文，
  更早的 `/init` 只给一句记录（record），不每轮重复几百字提示词；
- `/init 重点写测试命令` 这种后面带的话当补充要求接在提示词后面（两家都不收参数）；
- 已有非空 AGENTS.md（工作区根目录）→ 不调模型，回一句（decline）；空文件当没有（Gemini 先建空文件的那种半截状态）；
  指向工作区外的符号链接也算“已有”，不碰；
- 不建空文件：建了又失败会留下一个空 AGENTS.md，下次反而以为“已有”。
"""
import os

from .storage import project_file_root

COMMAND = "/init"
TARGET = "AGENTS.md"
NOTE_MAX = 500  # `/init` 后面补充要求最多收多少字

# Codex prompt_for_init_command.md（原文），末尾嫁接 Gemini 的非代码目录分支 + 我们的环境说明
PROMPT = """Generate a file named AGENTS.md that serves as a contributor guide for this repository.
Before writing, check whether AGENTS.md already exists in the current working directory. If it does, do not overwrite or modify it.
Your goal is to produce a clear, concise, and well-structured document with descriptive headings and actionable explanations for each section.
Follow the outline below, but adapt as needed — add sections if relevant, and omit those that do not apply to this project.

Document Requirements

- Title the document "Repository Guidelines".
- Use Markdown headings (#, ##, etc.) for structure.
- Keep the document concise. 200-400 words is optimal.
- Keep explanations short, direct, and specific to this repository.
- Provide examples where helpful (commands, directory paths, naming patterns).
- Maintain a professional, instructional tone.

Recommended Sections

Project Structure & Module Organization

- Outline the project structure, including where the source code, tests, and assets are located.

Build, Test, and Development Commands

- List key commands for building, testing, and running locally (e.g., npm test, make build).
- Briefly explain what each command does.

Coding Style & Naming Conventions

- Specify indentation rules, language-specific style preferences, and naming patterns.
- Include any formatting or linting tools used.

Testing Guidelines

- Identify testing frameworks and coverage requirements.
- State test naming conventions and how to run tests.

Commit & Pull Request Guidelines

- Summarize commit message conventions found in the project's Git history.
- Outline pull request requirements (descriptions, linked issues, screenshots, etc.).

(Optional) Add other sections if relevant, such as Security & Configuration Tips, Architecture Overview, or Agent-Specific Instructions.

If this workspace is not a code project (notes, documents, research, data), write instead: a Directory Overview (what it is for), Key Files (the most important files and what they hold) and Usage (how the contents are meant to be used).

Environment notes:
- "The current working directory" is the root of this conversation's workspace. Explore it with the file tools first (list the root, read the README if any, then up to 10 important files), and write AGENTS.md at the workspace root with write_file.
- If the workspace is empty, say so briefly and do not create the file.
- Write the document in the language the user writes to you in. When done, reply with one or two sentences on what the file covers."""

NOTE_HEAD = "Additional request from the user for this AGENTS.md:"
RECORD = "[用户之前用 /init 让你为工作区生成 AGENTS.md{note}]"
DECLINE = ("工作区根目录已经有 AGENTS.md 了，这次没改动它。想重写的话先删掉它再 /init，"
           "或者直接告诉我要改哪里。")


def parse(text: object) -> str | None:
    """整条消息是不是 `/init`（可带补充要求）：是 → 补充要求（没有就是 ""）；不是 → None。
    `/init` 后面必须是空白或结束（`/initial` 不算）；大小写不敏感（手机输入法常把首字母大写）。"""
    if not isinstance(text, str):
        return None
    t = text.strip()
    if t[:len(COMMAND)].lower() != COMMAND or (len(t) > len(COMMAND) and not t[len(COMMAND)].isspace()):
        return None
    return t[len(COMMAND):].strip()[:NOTE_MAX]


def of(blocks: list[dict]) -> str | None:
    """一条存库的用户消息是不是 `/init`：第一个块是文字且整段是命令（附件 / 技能引用跟在后面没关系）。"""
    if not blocks or blocks[0].get("type") != "text":
        return None
    return parse(blocks[0].get("text"))


def render(note: str) -> str:
    """当前这一问：给模型的完整提示词。"""
    return PROMPT + (f"\n\n{NOTE_HEAD}\n{note}" if note else "")


def record(note: str) -> str:
    """更早的 `/init`：历史里只留一句。"""
    return RECORD.format(note=f"（补充：{note}）" if note else "")


def existing(workspace: str) -> bool:
    """工作区根目录已有非空 AGENTS.md（或任何同名的东西：目录、符号链接）→ True。读不了也当已有（不冒险覆盖）。"""
    p = project_file_root(workspace) / TARGET
    if not os.path.lexists(p):
        return False
    if p.is_symlink() or not p.is_file():
        return True
    try:
        return bool(p.read_text(encoding="utf-8", errors="replace").strip())
    except OSError:
        return True
