#!/usr/bin/env python3
"""Assemble every ```asm``` snippet in the scripting docs, so they stay honest.

Each snippet is built as a standalone script with the real toolchain - the same
preprocess / enumproc / assemble / link chain that make_script_bin.sh runs - so
a command signature or constant name that has drifted shows up as a failure
here instead of in someone's map.

Names the docs invent for illustration (MyMap_Text_*, VAR_MY_QUEST_STATE, ...)
are defined below as placeholders; everything else has to resolve for real.

Requires a configured build directory (`make configure` or any prior build), as
the generated headers and enumproc live there.

Usage:  python3 tools/scripts/check_script_doc_snippets.py
"""

import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BUILD = os.path.join(ROOT, "build")
ENUMPROC = os.path.join(BUILD, "tools/enumproc/enumproc")

DOCS = ["docs/scripting/patterns.md", "docs/scripting/README.md"]

PLACEHOLDERS = """#include "macros/scrcmd.inc"
#include "res/field/events/events_twinleaf_town.h"

#define MyMap_Text_Hello 0
#define MyMap_Text_VillagerIntro 0
#define MyMap_Text_VillagerMidQuest 0
#define MyMap_Text_VillagerAfterDex 0
#define MyMap_Text_WouldYouLikeToRest 0
#define MyMap_Text_RestWell 0
#define MyMap_Text_MaybeNextTime 0
#define MyMap_Text_HereTakeThis 0
#define MyMap_Text_UseItWell 0
#define MyMap_Text_YouGotAnEevee 0
#define MyMap_Text_LeaderIntro 0
#define MyMap_Text_YouWin 0
#define MyMap_Text_ThereYouAre 0
#define MyMap_Text_ToOreburgh 0
#define MyMap_Text_TrainerTipsPotions 0
#define VAR_MY_QUEST_STATE VAR_0x8003
#define VAR_MY_CUTSCENE_STATE VAR_0x8003
#define FLAG_MY_QUEST_DONE FLAG_HAS_POKEDEX
#define FLAG_RECEIVED_MY_MAP_POTION FLAG_HAS_POKEDEX
#define FLAG_MY_MAP_LEADER_DEFEATED FLAG_HAS_POKEDEX
#define LOCALID_QUEST_GIVER LOCALID_COLLECTOR
#define MAP_HEADER_MY_CAVE MAP_HEADER_TWINLEAF_TOWN
"""

ENTRY_TABLE = """
    ScriptEntry Probe_Entry1
    ScriptEntryEnd

Probe_Entry1:
    End
"""

STUBBABLE = re.compile(r"^(MyMap_|TwinleafTown_)")
LABEL_ARG = re.compile(
    r"(?:GoTo|Call)(?:If\w+)?\s+(.*)$|"
    r"(?:ApplyMovement|InitScriptEntry_OnFrameTable|ScriptEntry)\s+(.*)$"
)


def referenced_labels(block):
    """Labels the snippet jumps to, whether or not it defines them."""
    names = set()
    for line in block.splitlines():
        match = LABEL_ARG.match(line.split("@")[0].strip())
        if match:
            argument = match.group(1) or match.group(2)
            names.add(argument.split(",")[-1].strip())
    return names


def build_source(block):
    """Wrap a doc snippet in whatever it needs to stand on its own."""
    defines = PLACEHOLDERS
    if "macros/scrcmd.inc" in block:
        # The snippet includes it itself; including twice redefines every macro.
        defines = "\n".join(
            line for line in PLACEHOLDERS.splitlines()
            if "macros/scrcmd.inc" not in line
        ) + "\n"

    has_table = "ScriptEntry" in block or "InitScriptEntry" in block
    defined = set(re.findall(r"^(\w+):", block, re.M))
    stubs = "".join(
        f"\n{name}:\n    End\n"
        for name in sorted(referenced_labels(block) - defined)
        if STUBBABLE.match(name)
    )
    return defines + ("" if has_table else ENTRY_TABLE) + "\n" + block + stubs


def check_snippet(source, workdir, tag):
    """Run the real preprocess/assemble/link chain. Returns an error, or None."""
    path = os.path.join(workdir, f"{tag}.s")
    open(path, "w", encoding="utf-8").write(source)

    preprocessed = subprocess.run(
        ["arm-none-eabi-gcc", "-E", "-x", "assembler-with-cpp",
         "-Iinclude", "-Iasm", "-Ibuild", path],
        cwd=ROOT, capture_output=True, text=True)
    if preprocessed.returncode != 0:
        return "preprocess", preprocessed.stderr

    expanded = subprocess.run(
        [ENUMPROC], input=preprocessed.stdout, capture_output=True, text=True)
    if expanded.returncode != 0:
        return "enumproc", expanded.stderr

    obj = os.path.join(workdir, f"{tag}.o")
    assembled = subprocess.run(
        ["arm-none-eabi-gcc", "-x", "assembler-with-cpp", "-o", obj, "-c", "-"],
        cwd=ROOT, input=expanded.stdout, capture_output=True, text=True)
    if assembled.returncode != 0:
        return "assemble", assembled.stderr

    # The real build links each object too; that is what catches an undefined
    # constant, which a bare assemble would leave as a relocation.
    linked = subprocess.run(
        ["arm-none-eabi-ld", obj, "-o", os.path.join(workdir, f"{tag}.elf")],
        cwd=ROOT, capture_output=True, text=True)
    if linked.returncode != 0:
        return "link", linked.stderr
    return None


def main():
    if not os.path.exists(ENUMPROC):
        print(f"error: {os.path.relpath(ENUMPROC, ROOT)} not found; "
              "configure or build the project first", file=sys.stderr)
        return 2

    failures = 0
    with tempfile.TemporaryDirectory() as workdir:
        for doc in DOCS:
            text = open(os.path.join(ROOT, doc), encoding="utf-8").read()
            for number, block in enumerate(re.findall(r"```asm\n(.*?)```", text, re.S), 1):
                tag = f"{os.path.basename(doc).replace('.', '_')}_{number}"
                result = check_snippet(build_source(block), workdir, tag)
                if result:
                    stage, message = result
                    failures += 1
                    print(f"FAIL {doc} block {number} ({stage}):")
                    for line in message.strip().splitlines()[:6]:
                        print(f"   {line}")
                else:
                    print(f"ok   {doc} block {number}")

    print(f"\n{failures} failing snippet(s)" if failures else "\nall snippets build")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
