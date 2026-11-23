"""Sorting a bash command that reads, writes, copies, deletes or packs files: the part of bashread.Sorter that
knows the file tools."""
from __future__ import annotations

import os
import posixpath
import re
import tarfile

from .bashtables import NOT_FILES, READS, SEARCHERS
from .bashwords import Word, _bundles, _texts
from .paths import _some, _unzip_overwrites
from .pstables import VERBED


class Files:
    """Mixed into bashread.Sorter, whose add(), touch(), blocked(), resolve(), args(), places(), reach() and run()
    these use."""

    def reads(self, low: str, words: list[Word | None]) -> None:
        searcher = low in SEARCHERS
        values, files = SEARCHERS[low] if searcher else (READS[low][2], "")
        texts = [t for t in _texts(words) if t is not None]
        flags, positional = self.args(words, values, files)
        if searcher and not any(t in ("-e", "-f", "--regexp", "--file") or t.startswith(("--regexp=", "--file="))
                                or _bundles(t, "ef") for t in texts):
            positional = positional[1:]
        if low == "jq":
            positional = positional[1:]
        what, default_cwd = ("search", False) if searcher else READS[low][:2]
        if low == "rg" and any(f.startswith(("--pre", "--search-zip")) or _bundles(f, "z") for f in flags):
            self.add("unknown", "program", "rg runs a program on every file it searches")
            return
        if low in ("sort", "uniq", "base64", "iconv", "shuf") and (
                any(f == "-o" or f.startswith("--output") for f in flags) or (low == "uniq" and len(positional) > 1)):
            self.output(low, words)
            return
        if (low == "base64" and any(f in ("-d", "-D", "--decode") for f in flags)) or (low == "xxd" and "-r" in flags):
            self.add("read", "decode", f"{low} decodes what it is given")
        recurse = (searcher and (low in ("rg", "ag", "ack") or any(
            f in ("-r", "-R", "--recursive") or _bundles(f, "rR") for f in flags))) or low in ("du", "tree") or (
            low == "ls" and any(_bundles(f, "R") or f == "--recursive" for f in flags))
        paths, globs, wild, unresolved = self.places(positional)
        if not paths and not unresolved:
            if not (default_cwd or (searcher and recurse)):
                self.add("read", what, f"{low} reads what comes down the pipeline")
                return
            paths, unresolved = ([self.cwd], False) if self.cwd else ([], True)
        verb = {"search": "searches", "look": "looks at"}.get(what, what + "s")
        self.touch("read", what, f"{verb} {_some(paths) or 'a folder known only as it runs'}", paths, recurse=recurse,
                   wild=wild, unresolved=unresolved, globs=globs or list(paths))

    def output(self, low: str, words: list[Word | None]) -> None:
        """sort -o, uniq IN OUT, base64 -o: reads its inputs and writes one file."""
        texts = _texts(words)
        out, kept = None, []
        n = 0
        while n < len(words):
            t = texts[n]
            if t == "-o" and n + 1 < len(words):
                out = texts[n + 1]
                n += 2
                continue
            if t is not None and t.startswith("--output"):
                out = t.split("=", 1)[1] if "=" in t else (texts[n + 1] if n + 1 < len(texts) else None)
                n += 1 if "=" in t else 2
                continue
            kept.append(words[n])
            n += 1
        _, positional = self.args(kept, READS[low][2])
        if out is None and low == "uniq" and len(positional) > 1:
            out = positional[-1].text if positional[-1] is not None else None
            positional = positional[:-1]
        sources, globs, wild, unresolved = self.places(positional)
        if sources or unresolved:
            self.touch("read", "read", f"reads {_some(sources)}", sources, wild=wild, unresolved=unresolved,
                       globs=globs or sources)
        self.write_to(out, f"{low} writes")

    def write_to(self, raw: str | None, why: str, append: bool = False, what: str = "write") -> None:
        if raw is None:
            self.add("unknown", "write", f"{why} to a file whose name is computed", unresolved=True, write=True)
            return
        if NOT_FILES.match(raw) or raw == "-":
            return
        place = self.resolve(raw)
        if place is None:
            self.add("unknown", "write", f"{why} in a folder known only as it runs", unresolved=True, write=True)
            return
        self.touch("overwrite" if os.path.isfile(place) and not append else "change", "append" if append else what,
                   f"{why} {place}", [place], write=True)

    def sed(self, words: list[Word | None]) -> None:
        texts = _texts(words)
        inplace = any(t is not None and (t.startswith(("-i", "--in-place")) or _bundles(t, "i")) for t in texts)
        given = any(t in ("-e", "--expression", "-f", "--file") for t in texts)
        scripts, files, take = [], [], False
        for t in texts:
            if take:
                scripts.append(t)
                take = False
            elif t in ("-f", "--file"):
                self.add("program", "script", "runs a sed script from a file")
                return
            elif t in ("-e", "--expression"):
                take = True
            elif t is not None and t.startswith("-") and len(t) > 1:
                continue
            elif not given and not scripts:
                scripts.append(t)
            else:
                files.append(t)
        for script in scripts:
            if script is None:
                self.add("unknown", "unknown", "runs a sed script computed as it runs")
                return
            # The s/// commands' patterns and replacements are text; what is left names the commands and flags.
            rest = re.sub(r"s(.)(?:\\.|(?!\1).)*\1(?:\\.|(?!\1).)*\1([A-Za-z0-9]*)",
                          lambda m: " " + re.sub(r"[gpiIm0-9]", "", m.group(2)) + " ", script)
            rest = re.sub(r"/(?:\\.|[^/])*/", " ", rest)
            if re.search(r"[ewWrRQ]", rest):
                self.add("unknown", "unknown", "runs a sed script that runs commands or reads and writes files")
                return
        paths, globs, wild, unresolved = self.places([Word(f) if f is not None else None for f in files])
        if inplace:
            self.touch("overwrite", "write", f"changes {_some(paths)} in place", paths, write=True, wild=wild,
                       unresolved=unresolved or not paths, globs=globs or paths)
        elif paths or unresolved:
            self.touch("read", "read", f"reads {_some(paths)}", paths, wild=wild, unresolved=unresolved,
                       globs=globs or paths)

    def awk(self, words: list[Word | None]) -> None:
        texts = _texts(words)
        program, files, take = "", [], False
        for t in texts:
            if take:
                take = False
            elif t in ("-v", "-F"):
                take = True
            elif t in ("-f", "--file", "-E"):
                self.add("program", "script", "runs an awk program from a file")
                return
            elif t is not None and (t.startswith("-i") or t == "--include"):
                self.add("overwrite", "write", "awk changes files in place or loads code", unresolved=True,
                         write=True)
                return
            elif t is not None and t.startswith("-") and len(t) > 1:
                continue
            elif program == "":
                program = t
            else:
                files.append(t)
        if program is None or re.search(r"system\s*\(|\|\s*(getline|&)|getline\s*<|(print|printf)[^;}]*[>|]|"
                                        r"close\s*\(|fflush\s*\(\s*\"", program):
            self.add("unknown", "unknown", "runs an awk program that runs commands or writes files")
            return
        paths, globs, wild, unresolved = self.places([Word(f) if f is not None else None for f in files])
        if paths or unresolved:
            self.touch("read", "read", f"reads {_some(paths)}", paths, wild=wild, unresolved=unresolved,
                       globs=globs or paths)

    def find(self, words: list[Word | None]) -> None:
        n = 0
        while n < len(words) and words[n] is not None and (words[n].text in ("-L", "-H", "-P")
                                                            or words[n].text.startswith("-O")):
            n += 1
        roots = []
        while n < len(words) and (words[n] is None or not words[n].text.startswith(("-", "(", "!", ")"))):
            roots.append(words[n])
            n += 1
        places, _, wild, unresolved = self.places(roots)
        if not places and not unresolved:
            places, unresolved = ([self.cwd], False) if self.cwd else ([], True)
        expression = words[n:]
        texts = _texts(expression)
        k = 0
        while k < len(texts):
            t = texts[k]
            if t in ("-exec", "-execdir", "-ok", "-okdir"):
                end = next((j for j in range(k + 1, len(texts)) if texts[j] in (";", "+")), len(texts))
                sub = [None if w is None or "{}" in w.text else w for w in expression[k + 1:end]]
                if not sub or sub[0] is None:
                    self.add("hidden", "hidden", "find runs a command whose name is computed")
                    return
                self.on_found(sub, places, unresolved)
                k = end + 1
                continue
            if t == "-delete":
                self.touch("delete", "delete", f"deletes what find finds under {_some(places)}", places, write=True,
                           recurse=True, wild=True, unresolved=True)
            elif t in ("-fprint", "-fprint0", "-fprintf", "-fls") and k + 1 < len(texts):
                self.write_to(texts[k + 1], "find writes its list to")
                k += 1
            elif t == "-files0-from" and k + 1 < len(texts):
                self.reads("cat", expression[k + 1:k + 2])
                k += 1
            k += 1
        self.touch("read", "list", f"lists {_some(places) or 'a folder known only as it runs'}", places, recurse=True,
                   wild=wild, unresolved=unresolved, globs=list(places))

    def on_found(self, sub: list[Word | None], places: list[str], unresolved: bool) -> None:
        """The command find -exec runs (`sub`, {} computed). What it runs on is each file found: any place under
        the folders searched. A read of them is as known as the folders are; a change or delete is known only as
        it runs."""
        before = len(self.acts)
        self.run(sub[0].text, sub[1:], [], {"kind": "", "text": None})
        ran, self.acts = self.acts[before:], self.acts[:before]
        for act in ran:
            if act.kind not in ("read", "change", "overwrite", "delete") or act.paths:
                self.acts.append(act)
                continue
            self.touch(act.kind, act.what, act.why.replace("places computed as it runs", _some(places)),
                       list(places), write=act.write, recurse=True, wild=True,
                       unresolved=unresolved or act.kind != "read", globs=list(places))

    def xargs(self, words: list[Word | None]) -> None:
        rest, marker = list(words), None
        while rest and rest[0] is not None:
            text = rest[0].text
            if text in ("-I", "--replace") and len(rest) > 1:
                marker = rest[1].text if rest[1] is not None else "{}"
                rest.pop(0)
            elif text.startswith(("-I", "--replace=")):
                marker = text[2:] if text.startswith("-I") else text.split("=", 1)[1]
            elif text == "-i":
                marker = "{}"
            elif text in ("-n", "-P", "-d", "-L", "-s", "-E", "-a", "-l", "--arg-file", "--max-args", "--delimiter",
                          "--max-procs") and len(rest) > 1:
                if text in ("-a", "--arg-file"):
                    self.reads("cat", rest[1:2])
                rest.pop(0)
            elif not text.startswith("-"):
                break
            rest.pop(0)
        if not rest:
            return
        if rest[0] is None:
            self.add("hidden", "hidden", "xargs runs a command whose name is computed")
            return
        # Its arguments come from its input: any value at all.
        args = [None if w is None or (marker and marker in w.text) else w for w in rest[1:]]
        self.run(rest[0].text, args + ([] if marker else [None]), [], {"kind": "pipe", "text": None})

    def copy(self, low: str, words: list[Word | None]) -> None:
        texts = [t for t in _texts(words) if t is not None]
        if low == "rsync" and any((re.match(r"^[^/]*[^/\\]:", t) or "://" in t) and not t.startswith("-")
                                  for t in texts):
            if any(t in ("-e", "--rsh") or t.startswith(("--rsh=", "-e")) for t in texts):
                self.add("system", "remote", "runs rsync through a remote shell")
                return
            host = next((t.split(":")[0].split("@")[-1] for t in texts if ":" in t and not t.startswith("-")), "")
            self.reach(host, True, f"copies files to or from {host} with rsync")
            return
        flags, positional = self.args(words, "tSmogT" if low == "install" else "tS", "t")
        if low == "install" and any(_bundles(f, "d") for f in flags):
            self.change_paths("change", "mkdir", "creates", positional)
            return
        target = next((f.split("=", 1)[1] for f in flags if f.startswith("--target-directory=")), None)
        if "-t" in flags or target is not None:
            # -t DIR names the destination first; args() kept DIR as the first positional word.
            dest_word = Word(target) if target is not None else (positional.pop(0) if positional else None)
        elif len(positional) >= 2:
            dest_word = positional.pop()
        else:
            self.add("unknown", "unknown", f"runs {low} without a place to copy or move to")
            return
        recurse = low in ("rsync", "ditto") or any(_bundles(f, "rRa") or f in ("--recursive", "--archive")
                                                   for f in flags)
        what = "move" if low == "mv" else "copy"
        sources, globs, wild, unresolved = self.places(positional)
        if self.protected_among(sources, what == "move", recurse, VERBED.get(what, what)):
            return
        dest = self.resolve(dest_word.text) if dest_word is not None else None
        named = _some(sources) or "files computed as it runs"
        if dest is None:
            self.add("change", what, f"{VERBED.get(what, what)} {named} to a place computed as it runs", paths=sources,
                     write=what == "move", wild=wild, unresolved=True, dest_unresolved=True, recurse=recurse)
            return
        refused = self.blocked(dest, True)
        if refused:
            self.add(refused, refused, f"{VERBED.get(what, what)} into {dest}, which is protected", paths=[dest])
            return
        overwrite = False
        if not wild and not unresolved and not any(f in ("-n", "--no-clobber", "--ignore-existing")
                                                   or _bundles(f, "n") for f in flags):
            for src in sources:
                landing = posixpath.join(dest, posixpath.basename(src)) if os.path.isdir(dest) else dest
                overwrite = overwrite or (os.path.isfile(landing) and landing != src)
        self.add("overwrite" if overwrite else "change", what, f"{VERBED.get(what, what)} {named} to {dest}",
                 paths=sources, dest=dest, write=what == "move", wild=wild, unresolved=unresolved, recurse=recurse,
                 globs=globs or list(sources))
        if low == "rsync" and any(f.startswith(("--delete", "--remove-source")) for f in flags):
            self.touch("delete", "delete", f"deletes files in {dest} that are not in {_some(sources)}", [dest],
                       write=True, recurse=True, wild=True, unresolved=True)

    def delete(self, low: str, words: list[Word | None]) -> None:
        flags, positional = self.args(words, "ns" if low == "shred" else "")
        if low == "shred" and not any(_bundles(f, "u") or f.startswith("--remove") for f in flags):
            self.change_paths("overwrite", "write", "overwrites", positional)
            return
        paths, globs, wild, unresolved = self.places(positional)
        if paths or unresolved:
            self.touch("delete", "delete", f"deletes {_some(paths) or 'places computed as it runs'}", paths,
                       write=True, recurse=any(_bundles(f, "rR") or f == "--recursive" for f in flags), wild=wild,
                       unresolved=unresolved, globs=globs or list(paths))

    def change_paths(self, kind: str, what: str, verb: str, positional: list, recurse: bool = False) -> None:
        paths, globs, wild, unresolved = self.places(positional)
        if not paths and not unresolved:
            return
        if kind == "change" and what == "write" and any(os.path.isfile(p) for p in paths):
            kind = "overwrite"
        self.touch(kind, what, f"{verb} {_some(paths) or 'places computed as it runs'}", paths, write=True,
                   wild=wild, unresolved=unresolved, recurse=recurse, globs=globs or list(paths))

    def change(self, low: str, words: list[Word | None]) -> None:
        if low == "mkdir":
            self.change_paths("change", "mkdir", "creates", self.args(words, "m")[1])
        elif low == "touch":
            self.change_paths("change", "newfile", "creates or touches", self.args(words, "rtd")[1])
        elif low == "truncate":
            self.change_paths("overwrite", "empty", "empties", self.args(words, "sr")[1])
        elif low == "tee":
            flags, positional = self.args(words)
            for word in positional:
                self.write_to(word.text if word is not None else None, "tee writes",
                              append=any(_bundles(f, "a") or f == "--append" for f in flags))
        elif low == "chmod":
            flags, positional = self.args(words)
            mode = positional[0].text if positional and positional[0] is not None else None
            if mode is None or re.search(r"[st]", mode) or re.fullmatch(r"0?[2-7][0-7]{3}", mode):
                self.add("system", "system", "chmod sets a mode that runs a program with its owner's rights")
                return
            self.change_paths("change", "attr", "changes the permissions of", positional[1:],
                              recurse=any(_bundles(f, "R") for f in flags))
        elif low == "dd":
            for t in _texts(words):
                if t is None:
                    self.add("unknown", "unknown", "runs dd with computed arguments")
                    return
                if t.startswith("if="):
                    self.reads("cat", [Word(t[3:])])
                elif t.startswith("of=") and t[3:].startswith("/dev/") and not NOT_FILES.match(t[3:]):
                    self.add("system", "device", f"writes straight to the device {t[3:]}")
                    return
                elif t.startswith("of="):
                    self.write_to(t[3:], "dd writes")
        elif low == "mktemp":
            self.add("change", "newfile", "creates an empty temporary file", write=True)
        elif low in ("split", "csplit"):
            _, positional = self.args(words, "lbnadf")
            self.reads("cat", positional[:1])
            prefix = positional[1].text if len(positional) > 1 and positional[1] is not None else "x"
            self.change_paths("change", "write", "writes pieces named", [Word(prefix + "*", True)])
        else:
            self.add("unknown", "write", "patch changes the files the patch names", unresolved=True, write=True)

    def archive(self, low: str, words: list[Word | None]) -> None:
        texts = _texts(words)
        if any(t is None for t in texts):
            self.add("unknown", "unknown", f"runs {low} with computed arguments", unresolved=True)
        elif low == "tar":
            self.tar(texts)
        elif low == "zip":
            self.zip_files(words)
        elif low == "unzip":
            self.unzip(words, texts)
        elif low in ("7z", "7za"):
            command = next((t for t in texts if not t.startswith("-")), "")
            if command in ("l", "t", "i", "h"):
                self.reads("cat", [Word(t) for t in texts if not t.startswith("-")][1:2])
            else:
                self.add("unknown", "write", f"runs 7z {command}", paths=[self.cwd] if self.cwd else [], write=True,
                         unresolved=True)
        else:
            flags, positional = self.args(words, "S")
            if any(_bundles(f, "cltk") or f in ("--stdout", "--list", "--test", "--keep") for f in flags):
                self.reads("cat", positional)
            else:
                self.change_paths("change", "write", "compresses or expands", positional)

    def zip_files(self, words: list[Word]) -> None:
        flags, positional = self.args(words, "xib")
        if not positional:
            return
        recurse = any(_bundles(f, "r") for f in flags)
        sources, globs, wild, unresolved = self.places(positional[1:])
        if self.protected_among(sources, False, recurse, "zips"):
            return
        if sources:
            self.add("read", "read", f"reads {_some(sources)}", paths=sources, wild=wild, globs=globs or sources,
                     recurse=recurse, unresolved=unresolved)
        self.write_to(positional[0].text, "zip writes", what="zip")

    def unzip(self, words: list[Word], texts: list[str]) -> None:
        flags, positional = self.args(words, "dx")
        if any(_bundles(f, "lvtZp") for f in flags):
            self.reads("cat", positional[:1])
            return
        out = texts[texts.index("-d") + 1] if "-d" in texts[:-1] else None
        archive = self.resolve(positional[0].text) if positional else None
        dest = self.resolve(out) if out else self.cwd
        if archive is None or dest is None:
            self.add("unknown", "unzip", "unzips into a place known only as it runs", unresolved=True, write=True)
            return
        refused = self.blocked(dest, True) or self.blocked(archive, False)
        if refused:
            self.add(refused, refused, f"unzips {archive} into {dest}, which is protected", paths=[dest])
            return
        replaces = os.path.exists(archive) and _unzip_overwrites(archive, dest)
        self.add("overwrite" if replaces else "change", "unzip", f"unzips {archive} to {dest}", paths=[archive],
                 dest=dest)

    def protected_among(self, places: list[str], write: bool, deep: bool, doing: str) -> bool:
        """Refuses the first protected place among `places` ("<doing> <place>, which is protected"): True when
        there is one."""
        for place in places:
            refused = self.blocked(place, write, deep=deep)
            if refused:
                self.add(refused, refused, f"{doing} {place}, which is protected", paths=[place])
                return True
        return False

    def tar(self, texts: list[str]) -> None:
        """tar: what it packs (read whole) and writes, what it unpacks where, or the archive it lists."""
        options = _tar_options(texts)
        if options is None:
            self.add("hidden", "hidden", "tar runs a program it is given")
            return
        mode, archive, dest, sources = options
        if set(mode) & set("cru"):
            places, globs, wild, unresolved = self.places([Word(s) for s in sources])
            if self.protected_among(places, False, True, "archives"):
                return
            if places:
                self.add("read", "read", f"reads {_some(places)}", paths=places, recurse=True, wild=wild,
                         globs=globs or places, unresolved=unresolved)
            self.write_to(archive, "tar writes", what="zip")
        elif "x" in mode:
            place = self.resolve(archive) if archive else None
            target = self.resolve(dest) if dest else self.cwd
            if place is None or target is None:
                self.add("unknown", "unzip", "unpacks an archive in a place known only as it runs", unresolved=True,
                         write=True)
                return
            refused = self.blocked(target, True) or self.blocked(place, False)
            if refused:
                self.add(refused, refused, f"unpacks {place} into {target}, which is protected", paths=[target])
                return
            self.add("overwrite" if _tar_overwrites(place, target) else "change", "unzip",
                     f"unpacks {place} to {target}", paths=[place], dest=target)
        else:
            self.reads("cat", [Word(archive)] if archive else [])


def _tar_options(texts: list[str]) -> tuple[str, str | None, str | None, list[str]] | None:
    """(the mode letters among c x t r u, the archive, the folder -C names, the files named) of tar's words; None
    when an option runs a program."""
    if texts and re.fullmatch(r"[A-Za-z]+", texts[0]):
        texts = ["-" + texts[0], *texts[1:]]
    mode, archive, dest, sources, n = "", None, None, [], 0
    longs = {"--create": "c", "--extract": "x", "--get": "x", "--list": "t", "--append": "r", "--update": "u",
             "--delete": "x"}
    while n < len(texts):
        t = texts[n]
        if t.startswith(("--to-command", "--use-compress-program", "--checkpoint-action", "--info-script",
                         "--new-volume-script", "-I", "--rsh-command", "--rmt-command", "-F")):
            return None
        if t in longs:
            mode += longs[t]
        elif t.startswith("--file="):
            archive = t.split("=", 1)[1]
        elif t in ("-C", "--directory") and n + 1 < len(texts):
            dest = texts[n + 1]
            n += 1
        elif t in ("-f", "--file") and n + 1 < len(texts):
            archive = texts[n + 1]
            n += 1
        elif t.startswith("--directory="):
            dest = t.split("=", 1)[1]
        elif re.fullmatch(r"-[A-Za-z]+", t):
            mode += "".join(c for c in t[1:] if c in "cxtru")
            if "f" in t[1:] and n + 1 < len(texts):
                archive = texts[n + 1]
                n += 1
        elif not t.startswith("-"):
            sources.append(t)
        n += 1
    return mode, archive, dest, sources


def _tar_overwrites(archive: str, dest: str) -> bool:
    """Unpacking would replace a file already in `dest`, or put one outside it."""
    try:
        with tarfile.open(archive, "r:*") as t:
            names = t.getnames()
    except (OSError, tarfile.TarError):
        return True
    return any(n.startswith("/") or ".." in n.split("/") or os.path.isfile(posixpath.join(dest, n)) for n in names)

