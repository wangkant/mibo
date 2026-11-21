"""Reading a bash command before it runs, and sorting what it would do (macOS and Linux).

tree-sitter-bash parses it, the grammar other coding agents read bash with. Every command at any depth is sorted
into read.py's acts: lists, pipelines, subshells, loops, function bodies, command and process substitutions,
here-documents, `bash -c '...'` and what `find -exec` and `xargs` run. Paths are made absolute with `~`, $HOME,
`..` and the folder each `cd` reaches; a name, path or code computed only as it runs is unresolved. The tables
are read.py's, with the POSIX commands and places beside them here. Whatever the grammar or the tables do not
know is "unknown", and a command that does not parse comes back with errors: neither runs without the person's
press. `read.judge` then holds the acts against the grants as it does for PowerShell.
"""
from __future__ import annotations

import fnmatch
import functools
import glob as globlib
import os
import posixpath
import re
import tarfile
from urllib.parse import urlsplit

from .grants import SECRET_NAMES, SECRET_SUFFIXES
from .read import (
    COMMAND_MAX,
    EXE_INSTALL,
    GIT_NET,
    INSTALLERS,
    INTERPRETERS,
    NEVER_KINDS,
    OPEN_RISKY,
    RUNNABLE,
    VERBED,
    Act,
    Reading,
    _local_host,
    _some,
    _unzip_overwrites,
)

# The name a process substitution's pipe gets in an argument.
PIPE = "/dev/fd/63"
# How deep `bash -c` inside `bash -c` is read before it counts as hidden.
DEPTH_MAX = 4

# ---------------------------------------------------------------- tables

# No effect outside the command, and no file named.
PURE = {
    "echo", "printf", "true", "false", ":", "test", "[", "expr", "seq", "sleep", "yes", "basename", "dirname", "pwd",
    "uname", "whoami", "id", "groups", "nproc", "getconf", "locale", "tty", "arch", "logname", "users", "cal",
    "factor", "type", "which", "whereis", "jobs", "wait", "umask", "ulimit", "shopt", "set", "read", "mapfile",
    "readarray", "shift", "getopts", "break", "continue", "return", "exit", "dirs", "times", "tr", "bc", "clear",
    "tput", "unalias", "hash", "help", "history", "pbcopy", "wl-copy", "printenv", "let", "units", "cowsay",
}
# Facts about this computer, named by no path.
FACTS = {
    "ps": "apps", "pgrep": "apps", "top": "apps", "htop": "apps", "lsof": "apps", "uptime": "info", "free": "info",
    "vmstat": "info", "vm_stat": "info", "iostat": "info", "lscpu": "info", "lsblk": "disk", "lsusb": "info",
    "lspci": "info", "lsmod": "info", "sw_vers": "info", "system_profiler": "info", "ioreg": "info", "df": "disk",
    "netstat": "info", "ss": "info", "dmesg": "info", "journalctl": "info", "who": "info", "w": "info",
    "last": "info", "lsb_release": "info", "mdfind": "info", "nvidia-smi": "info",
}
# Commands that read the files named among their arguments: (what, whether no file means the folder it runs in,
# short options that take a value).
READS = {
    "cat": ("read", False, ""), "head": ("read", False, "nc"), "tail": ("read", False, "ncs"),
    "wc": ("read", False, ""), "less": ("read", False, ""), "more": ("read", False, ""), "nl": ("read", False, "wsvbi"),
    "od": ("read", False, "NjtAw"), "xxd": ("read", False, "lscg"), "hexdump": ("read", False, "nse"),
    "strings": ("read", False, "nte"), "diff": ("read", False, "UCLIx"), "cmp": ("read", False, "in"),
    "comm": ("read", False, ""), "md5sum": ("read", False, ""), "sha1sum": ("read", False, ""),
    "sha256sum": ("read", False, ""), "sha512sum": ("read", False, ""), "shasum": ("read", False, "a"),
    "md5": ("read", False, "s"), "cksum": ("read", False, ""), "b2sum": ("read", False, ""), "sum": ("read", False, ""),
    "cut": ("read", False, "dfcb"), "tac": ("read", False, ""), "rev": ("read", False, ""),
    "fold": ("read", False, "w"),
    "fmt": ("read", False, "w"), "paste": ("read", False, "d"), "join": ("read", False, "12jtoe"),
    "column": ("read", False, "tsc"), "expand": ("read", False, "t"), "unexpand": ("read", False, "t"),
    "pr": ("read", False, "wlh"), "zcat": ("read", False, ""), "gzcat": ("read", False, ""),
    "bzcat": ("read", False, ""), "xzcat": ("read", False, ""), "numfmt": ("read", False, ""),
    "file": ("look", False, "mfP"), "stat": ("look", False, "fct"), "realpath": ("look", False, ""),
    "readlink": ("look", False, ""), "lsattr": ("look", False, ""), "getfacl": ("look", False, ""),
    "mdls": ("look", False, "n"), "ls": ("list", True, "IwT"), "dir": ("list", True, ""), "tree": ("list", True, "LIP"),
    "du": ("list", True, "dBt"), "uniq": ("read", False, "fsw"), "sort": ("read", False, "ktST"),
    "base64": ("read", False, "bw"), "jq": ("read", False, ""), "look": ("read", False, ""),
    "iconv": ("read", False, "ftc"), "shuf": ("read", False, "nir"), "xmllint": ("read", False, ""),
}
# The searchers: their first word is the pattern unless one is given by option (-e, -f); short options that take
# a value, and those whose value is a file read.
SEARCHERS = {"grep": ("ABCmefd", "f"), "egrep": ("ABCmefd", "f"), "fgrep": ("ABCmefd", "f"),
             "zgrep": ("ABCmef", "f"), "rg": ("ABCmegtTjMf", "f"), "ag": ("ABCmG", ""), "ack": ("ABC", "")}
# Wrappers that run the command after their own options; the options of theirs that take a value.
WRAPPERS = {"env": "uSC", "nice": "n", "time": "", "timeout": "sk", "stdbuf": "ioe", "command": "", "builtin": "",
            "exec": "a", "caffeinate": "tw", "ionice": "cnp", "chronic": "", "unbuffer": "", "watch": "nd"}
SHELLS = {"sh", "bash", "dash", "rbash"}
# Shells whose syntax this parser does not read: hidden, as read.py takes cmd and bash on Windows.
OTHER_SHELLS = {"zsh", "ksh", "mksh", "fish", "csh", "tcsh", "pwsh", "powershell", "xonsh", "nu", "elvish"}
INTERPRETERS_POSIX = set(INTERPRETERS) | {"nodejs", "lua", "luajit", "rscript", "r", "julia", "tclsh", "wish",
                                          "irb", "ipython", "jshell", "groovy", "scala", "swift", "elixir", "erl",
                                          "racket", "guile", "sbcl", "ts-node", "tsx"}
# The letters that give an interpreter code on the command line, alone or bundled (perl -ne, python -Bc).
INLINE = {"python": "c", "perl": "eE", "ruby": "e", "node": "ep", "nodejs": "ep", "deno": "", "bun": "e",
          "php": "rBRFE", "ipython": "c", "guile": "c", "ts-node": "ep", "java": "", "javaw": "", "jshell": "",
          "sbcl": "", "tclsh": "", "wish": ""}
INLINE_LONG = ("--eval", "--print", "--command", "--execute", "--exec", "--expr", "eval")
NETWORK = {"curl", "wget", "nc", "ncat", "netcat", "socat", "ping", "ping6", "traceroute", "traceroute6",
           "tracepath", "mtr", "dig", "host", "nslookup", "whois", "ftp", "tftp", "lftp", "http", "https", "xh",
           "aria2c", "drill", "axel"}
# Their short options that take a value, so the value is not taken for a host.
NET_VALUES = {"ping": "cisWtlIwQ", "ping6": "cisWtlIw", "traceroute": "mqfwpszgiN", "mtr": "cisa",
              "dig": "bfpqtcky", "nc": "pswqiTxX", "ncat": "pswix", "netcat": "pswqi", "whois": "hp",
              "nslookup": "", "host": "tWcR", "socat": ""}
CURL_VALUES = ("-o", "-d", "-H", "-X", "-u", "-A", "-e", "-b", "-c", "-T", "-F", "-K", "-w", "-m", "-r", "-x", "-D",
               "-E", "-U", "-y", "-Y", "-z", "-C", "-Q", "-t", "-P")
WGET_VALUES = ("-O", "-o", "-a", "-P", "-i", "-t", "-T", "-w", "-U", "-e", "-l", "-A", "-R", "-D", "-I", "-X", "-B",
               "-Q")
FETCH_LONG = {"--output", "--data", "--data-binary", "--data-raw", "--data-urlencode", "--data-ascii", "--header",
              "--request", "--user", "--user-agent", "--referer", "--cookie", "--cookie-jar", "--upload-file",
              "--form", "--form-string", "--config", "--max-time", "--connect-timeout", "--retry", "--proxy",
              "--resolve", "--cacert", "--cert", "--key", "--dump-header", "--trace", "--trace-ascii",
              "--output-dir", "--json", "--variable", "--url", "--directory-prefix", "--post-data", "--post-file",
              "--method", "--body-data", "--body-file", "--input-file", "--output-document", "--output-file",
              "--append-output", "--level", "--tries", "--timeout", "--save-cookies", "--load-cookies", "--password",
              "--http-user", "--http-password", "--certificate", "--private-key", "--execute", "--accept",
              "--reject", "--limit-rate", "--wait", "--dir", "--out"}
FETCH_OUT = {"-o", "--output", "--output-document", "-c", "--cookie-jar", "-D", "--dump-header", "--trace",
             "--trace-ascii", "--save-cookies", "--output-file", "--append-output", "-a", "--out"}
FETCH_IN = {"-T", "--upload-file", "--post-file", "--body-file", "--config", "-K", "--cert", "-E", "--key",
            "--load-cookies", "-i", "--input-file", "--certificate", "--private-key", "--cacert"}
FETCH_SENDS = {"-d", "--data", "--data-binary", "--data-raw", "--data-urlencode", "--data-ascii", "-F", "--form",
               "--form-string", "--post-data", "--post-file", "--body-data", "--body-file", "--json", "-T",
               "--upload-file", "-H", "--header", "-u", "--user", "-b", "--cookie", "-e", "--referer", "-A",
               "--user-agent", "--password", "--http-user", "--http-password", "-U"}
INSTALL = set(EXE_INSTALL) | {"apt", "apt-get", "aptitude", "dnf", "yum", "pacman", "zypper", "apk", "brew", "port",
                              "snap", "flatpak", "pipx", "uv", "go", "gem", "dpkg", "rpm", "installer",
                              "softwareupdate", "mas", "nix-env", "nix", "emerge", "xbps-install", "poetry", "pdm",
                              "rustup", "nvm", "bundle", "composer", "luarocks", "cpan", "cpanm", "bun"}
# Install tools' words that only list or tell, and those that only search a catalogue online.
INSTALL_READ = {"list", "ls", "--version", "-v", "-V", "version", "freeze", "show", "info", "check", "policy",
                "outdated", "doctor", "config", "env", "-l", "-q", "-qa", "-qi", "-ql", "-s", "-L", "--list", "-Q",
                "-Qi", "-Ql", "query", "why", "deps", "leaves", "audit", "--help", "help"}
INSTALL_SEARCH = {"search", "view", "-Ss", "find"}
# Their words that build, test or run the project rather than install: a program run.
BUILD_WORDS = {"run", "build", "test", "start", "fmt", "vet", "check", "clippy", "bench", "doc", "tool", "lint",
               "compile", "serve", "dev", "watch"}
# Running these downloads a package and runs it at once.
DOWNLOAD_RUN = {"npx", "pnpx", "bunx", "uvx", "yarn dlx", "pipx run", "pnpm dlx", "npm exec", "npm x", "pnpm exec",
                "bun x"}
# Build tools, test runners and editors: a program run, asked.
PROGRAMS = {"make", "gmake", "cmake", "ninja", "gcc", "g++", "cc", "c++", "clang", "clang++", "javac", "rustc", "tsc",
            "mvn", "gradle", "ant", "meson", "bazel", "scons", "xcodebuild", "swiftc", "zig", "gofmt", "rustfmt",
            "black", "ruff", "prettier", "eslint", "pytest", "tox", "nox", "jest", "mocha", "rake", "pod",
            "vim", "vi", "nvim", "nano", "emacs", "code", "subl", "gedit", "kate", "micro", "hx", "pico", "ed", "ex",
            "mate", "xed", "ffmpeg", "ffprobe", "convert", "magick", "pandoc", "sqlite3", "psql", "mysql", "redis-cli",
            "mongosh", "terraform", "ansible", "ansible-playbook", "hugo", "jekyll", "gh", "glab", "hub", "pre-commit",
            "mypy", "pylint", "flake8", "isort", "yapf", "shellcheck", "shfmt", "lsof-kill", "xdotool", "wmctrl",
            "notify-send", "say", "afplay", "screencapture", "pdftotext", "exiftool", "identify", "qpdf", "gs",
            "lp", "lpr", "rclone", "restic", "borg", "duplicity", "nmap", "tcpdump", "wireshark", "tshark"}
NEVER = {
    "sudo": "elevate", "su": "elevate", "doas": "elevate", "pkexec": "elevate", "run0": "elevate",
    "sudoedit": "elevate", "gksudo": "elevate", "gksu": "elevate", "kdesu": "elevate", "kdesudo": "elevate",
    "newgrp": "elevate", "sg": "elevate", "chroot": "elevate", "nsenter": "elevate", "unshare": "elevate",
    "shutdown": "shutdown", "reboot": "shutdown", "halt": "shutdown", "poweroff": "shutdown", "logout": "shutdown",
    "init": "shutdown", "telinit": "shutdown",
    "eval": "hidden", "osascript": "hidden", "nohup": "hidden", "setsid": "hidden", "disown": "hidden",
    "screen": "hidden", "tmux": "hidden", "byobu": "hidden", "at": "hidden", "batch": "hidden", "daemonize": "hidden",
    "coproc": "hidden", "enable": "hidden", "expect": "hidden", "busybox": "hidden", "toybox": "hidden",
    "script": "hidden", "dc": "hidden", "parallel": "hidden", "systemd-run": "hidden", "fc": "hidden",
    "iptables": "system", "ip6tables": "system", "nft": "system", "ufw": "system", "pfctl": "system",
    "firewall-cmd": "system", "socketfilterfw": "system", "umount": "system", "mkfs": "system", "fdisk": "system",
    "sfdisk": "system", "parted": "system", "gdisk": "system", "wipefs": "system", "mkswap": "system",
    "swapon": "system", "swapoff": "system", "fsck": "system", "e2fsck": "system", "tune2fs": "system",
    "resize2fs": "system", "losetup": "system", "cryptsetup": "system", "dmsetup": "system", "lvm": "system",
    "blkdiscard": "system", "useradd": "system", "usermod": "system", "userdel": "system", "groupadd": "system",
    "groupdel": "system", "passwd": "system", "chpasswd": "system", "chsh": "system", "chfn": "system",
    "gpasswd": "system", "visudo": "system", "vipw": "system", "dscl": "system", "dseditgroup": "system",
    "sysadminctl": "system", "modprobe": "system", "insmod": "system", "rmmod": "system", "kextload": "system",
    "kextunload": "system", "kmutil": "system", "csrutil": "system", "spctl": "system", "nvram": "system",
    "bless": "system", "systemsetup": "system", "tccutil": "system", "profiles": "system", "fdesetup": "system",
    "update-rc.d": "system", "chkconfig": "system", "service": "system", "rc-service": "system",
    "rc-update": "system", "grub-install": "system", "update-grub": "system", "grub-mkconfig": "system",
    "efibootmgr": "system", "setenforce": "system", "semanage": "system", "apparmor_parser": "system",
    "aa-complain": "system", "setcap": "system", "chown": "system", "chgrp": "system", "chattr": "system",
    "setfacl": "system", "chflags": "system", "ssh": "system", "scp": "system", "sftp": "system", "telnet": "system",
    "rlogin": "system", "rsh": "system", "iwconfig": "system", "wpa_cli": "system", "ln": "system", "link": "system",
    "update-alternatives": "system", "ldconfig": "system", "authconfig": "system", "mkfifo": "system",
    "mknod": "system", "brctl": "system", "tc": "system", "ethtool": "system", "kwriteconfig5": "system",
    "kwriteconfig6": "system", "plutil": "system",
    "security": "secrets", "secret-tool": "secrets", "kwallet-query": "secrets", "kwalletcli": "secrets",
    "gnome-keyring-daemon": "secrets", "pass": "secrets", "gopass": "secrets", "ssh-add": "secrets",
    "ssh-keygen": "secrets", "ssh-agent": "secrets", "ssh-keyscan": "secrets", "keyctl": "secrets", "gpg": "secrets",
    "gpg2": "secrets", "gpg-agent": "secrets", "op": "secrets", "bw": "secrets", "lpass": "secrets",
    "keepassxc-cli": "secrets", "dumpkeys": "secrets",
}
# System tools whose first word (or option) only reads; any other use changes the system.
SYSTEM_READ = {
    "systemctl": {"status", "show", "list-units", "list-unit-files", "list-timers", "list-sockets", "is-active",
                  "is-enabled", "is-failed", "cat", "--version", "list-dependencies", "help"},
    "launchctl": {"list", "print", "print-disabled", "blame", "version", "managername", "getenv", "procinfo"},
    "crontab": {"-l"}, "defaults": {"read", "read-type", "domains", "find", "help"},
    "diskutil": {"list", "info", "activity", "listfilesystems", "apfs", "cs"}, "hdiutil": {"info", "imageinfo"},
    "scutil": {"--get", "--dns", "--proxy", "--nwi"}, "pmset": {"-g"}, "hostnamectl": {"status"},
    "timedatectl": {"status", "list-timezones", "show"}, "localectl": {"status", "list-locales", "list-keymaps"},
    "loginctl": {"list-sessions", "show-session", "list-users", "session-status", "user-status"},
    "nmcli": {"general", "g", "device", "d", "dev", "connection", "c", "con", "radio", "monitor", "-t", "-f", "-p"},
    "networksetup": set(), "xattr": {"-l", "-p", "-x", "-h"}, "mount": {"-l"},
    "route": {"-n", "print", "get", "show", "-nr"}, "arp": {"-a", "-n", "-an"}, "ifconfig": set(),
    "ip": {"addr", "a", "address", "link", "l", "route", "r", "neigh", "n", "rule", "maddr", "-br", "-c", "-4", "-6",
           "-s", "-j", "show", "list", "ls"},
    "sysctl": {"-a", "-n", "-e", "-N", "-h"}, "date": set(), "hostname": {"-f", "-s", "-i", "-I", "-d", "-A"},
    "gsettings": {"get", "list-keys", "list-schemas", "list-recursively", "range", "describe", "writable",
                  "list-children", "list-relocatable-schemas", "monitor", "help"},
    "dconf": {"read", "list", "dump", "watch", "help"}, "xdg-settings": {"get", "check", "--help", "--list"},
}
# Those that only read when given no words at all.
SYSTEM_BARE = {"systemctl", "loginctl", "timedatectl", "hostnamectl", "localectl", "nmcli", "ip", "ifconfig",
               "mount", "date", "hostname", "sysctl", "route", "arp"}
# Words after `ip addr`, `nmcli connection` and the like that change things.
SYSTEM_VERBS = {"add", "del", "delete", "set", "flush", "change", "replace", "up", "down", "modify", "edit", "load",
                "reload", "import", "export", "on", "off", "connect", "disconnect", "rename", "append", "prepend",
                "save", "restore", "exec"}
# Variables that change what a command runs or loads, or how later words are split and looked up.
DANGEROUS_VARS = re.compile(
    r"^(PATH|LD_\w+|DYLD_\w+|BASH_ENV|ENV|PROMPT_COMMAND|IFS|PS4|SHELLOPTS|BASHOPTS|GLOBIGNORE|CDPATH|HOME|"
    r"PYTHON(PATH|STARTUP|HOME|INSPECT)|NODE_OPTIONS|NODE_PATH|PERL5OPT|PERL5LIB|PERLLIB|RUBYOPT|RUBYLIB|"
    r"GIT_\w+|PAGER|EDITOR|VISUAL|LESSOPEN|LESSCLOSE|MANPAGER|BROWSER|SSH_ASKPASS|SUDO_ASKPASS|BASH_FUNC_\w+|"
    r"TERMINFO|LOCPATH|GCONV_PATH|MALLOC_\w+|JAVA_TOOL_OPTIONS|_JAVA_OPTIONS|CLASSPATH|GEM_\w+|BUNDLE_\w+|"
    r"npm_config_\w+|NPM_CONFIG_\w+|PIP_\w+|XDG_CONFIG_HOME|ZDOTDIR)$")
# Places on macOS and Linux that a command may never change.
SYSTEM_PLACES = ("/etc", "/usr", "/bin", "/sbin", "/lib", "/lib32", "/lib64", "/libx32", "/boot", "/opt", "/srv",
                 "/var", "/root", "/System", "/Library", "/Applications", "/private", "/dev", "/proc", "/sys", "/snap",
                 "/nix", "/run", "/cores", "/efi")
# Inside those, the temporary places, which are not the system's.
TEMP_PLACES = ("/tmp", "/var/tmp", "/private/tmp", "/var/folders", "/private/var/folders", "/dev/shm", "/run/user")
# The top level folders that hold the person's own files.
OWN_TOPS = ("/home", "/Users", "/Volumes", "/media", "/mnt")
# Places whose contents are keys or passwords, read or written.
SECRET_PLACES = ("/etc/shadow", "/etc/gshadow", "/etc/sudoers", "/etc/sudoers.d", "/etc/ssh", "/etc/ssl/private",
                 "/root", "/var/db/sudo", "/private/etc/sudoers", "/private/etc/ssh", "/private/var/db/sudo",
                 "/Library/Keychains", "/var/lib/sss", "/etc/krb5.keytab", "/dev/mem", "/dev/kmem", "/proc/kcore",
                 "/private/etc/master.passwd", "/etc/master.passwd")
SECRET_PATTERNS = re.compile(r"^/proc/[^/]+/(environ|mem|maps|cmdline|root|cwd|fd)(/.*)?$")
# Redirection targets that are not files.
NOT_FILES = re.compile(r"^/dev/(null|stdout|stderr|stdin|tty|zero|u?random|fd/\d+)$")
# What opening a file in its own program runs, beyond Windows' list.
OPEN_RISKY_POSIX = OPEN_RISKY + (".app", ".command", ".tool", ".pkg", ".mpkg", ".dmg", ".desktop", ".appimage",
                                 ".deb", ".rpm", ".run", ".terminal", ".workflow", ".scpt", ".applescript",
                                 ".scptd", ".prefpane", ".kext", ".mobileconfig", ".webloc", ".inetloc", ".bash",
                                 ".zsh", ".csh", ".ksh", ".pl", ".rb", ".php")
SCRIPTS = RUNNABLE + (".bash", ".zsh", ".pl", ".rb", ".php", ".lua", ".r", ".command", ".tcl", ".awk", ".sed")
PACKAGES = INSTALLERS + (".pkg", ".mpkg", ".deb", ".rpm", ".appimage", ".run", ".dmg", ".snap", ".flatpakref")
# The folders whose programs are the system's own, so /bin/rm is rm.
BIN_DIRS = ("/bin", "/usr/bin", "/sbin", "/usr/sbin", "/usr/local/bin", "/usr/local/sbin", "/opt/homebrew/bin",
            "/opt/homebrew/sbin", "/run/current-system/sw/bin")
# Brace expansion ({a,b}, {1..3}) makes more than one word.
BRACES = re.compile(r"\{[^{}]*(,|\.\.)[^{}]*\}")
# What a variable may hold in arithmetic without running anything.
NUMERIC_VALUES = re.compile(r"-?\d+|\{-?\d+\.\.-?\d+(\.\.-?\d+)?\}")


def _reaches(p: list[str], root: list[str], deep: bool) -> bool:
    """A wildcard path, split into its parts, matches `root` or something inside it (or, with `deep`, a folder
    above it)."""
    n = min(len(p), len(root))
    if not all(fnmatch.fnmatchcase(root[i], p[i]) for i in range(n)):
        return False
    return len(p) >= len(root) or deep


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


@functools.lru_cache(maxsize=1)
def _language():
    import tree_sitter_bash
    from tree_sitter import Language
    return Language(tree_sitter_bash.language())


def _tree(text: str):
    from tree_sitter import Parser
    return Parser(_language()).parse(text.encode("utf-8")).root_node


def _text(node) -> str:
    return node.text.decode("utf-8", "replace")


def _short(texts: list[str | None]) -> str:
    return " ".join(t if t is not None else "?" for t in texts)[:120]


def _bundles(word: str, letters: str) -> bool:
    """A short option bundle (-Bc, -ne) holding one of `letters`."""
    return bool(letters) and bool(re.fullmatch(r"-[A-Za-z]+", word)) and any(c in word[1:] for c in letters)


def _numeric(node) -> bool:
    """A value that can only be a number: a number written out, {1..3}, or what `seq` prints."""
    if node.type == "command_substitution":
        inner = node.named_children[0] if node.named_children else None
        name = inner.child_by_field_name("name") if inner is not None and inner.type == "command" else None
        return name is not None and _text(name) == "seq"
    return node.type in ("number", "brace_expression") or NUMERIC_VALUES.fullmatch(_text(node)) is not None


def _descendants(node):
    stack = [node]
    while stack:
        item = stack.pop()
        yield item
        stack.extend(item.children)


def _texts(words: list) -> list[str | None]:
    return [w.text if w is not None else None for w in words]


class Word:
    """One argument after expansion: its text, and whether unquoted wildcards make it a pattern."""

    def __init__(self, text: str, wild: bool = False):
        self.text, self.wild = text, wild


# ---------------------------------------------------------------- sorting

class Sorter:
    def __init__(self, cwd: str | None, home: str, depth: int = 0):
        self.cwd = posixpath.normpath(cwd) if cwd else None
        self.home = posixpath.normpath(home)
        self.depth = depth
        self.acts: list[Act] = []
        self.consts: dict[str, str] = {}
        # Variables that may hold something other than a number written in the command: arithmetic on them can
        # run code written in their value.
        self.unsafe: set[str] = set()
        # Variables assigned once, outside loops, functions and subshells: their value is known where it is set.
        self.once: set[str] = set()
        self.stack: list[str | None] = []
        # Functions defined at the top level before this point: a call runs the body, sorted where it stands.
        self.funcs: set[str] = set()

    # ------------------------------------------------------------ before sorting

    def survey(self, root) -> None:
        counts: dict[str, int] = {}

        def note(name: str, value, apart: bool) -> None:
            counts[name] = counts.get(name, 0) + (2 if apart else 1)
            if value is None or not _numeric(value):
                self.unsafe.add(name)

        def walk(node, apart: bool) -> None:
            kind = node.type
            inside = apart or kind in ("for_statement", "c_style_for_statement", "while_statement",
                                       "function_definition", "subshell", "command_substitution",
                                       "process_substitution") or (kind == "pipeline" and node.named_child_count > 1)
            if kind == "variable_assignment":
                name = node.child_by_field_name("name")
                if name is not None:
                    prefix = node.parent is not None and node.parent.type == "command"
                    note(_text(name), node.child_by_field_name("value"), inside or prefix)
            elif kind == "for_statement":
                var = node.child_by_field_name("variable")
                values = node.children_by_field_name("value")
                if var is not None:
                    counts[_text(var)] = 2
                    if not values or not all(_numeric(v) for v in values):
                        self.unsafe.add(_text(var))
            elif kind == "command":
                name = node.child_by_field_name("name")
                if name is not None and _text(name) in ("read", "mapfile", "readarray", "getopts", "printf", "declare",
                                                        "local", "export"):
                    for word in node.children_by_field_name("argument"):
                        text = _text(word)
                        if re.fullmatch(r"[A-Za-z_]\w*", text):
                            self.unsafe.add(text)
                            counts[text] = 2
            for child in node.children:
                walk(child, inside)

        walk(root, False)
        self.once = {name for name, n in counts.items() if n == 1}

    # ------------------------------------------------------------ acts

    def add(self, kind: str, what: str, why: str, **more) -> Act:
        act = Act(kind, what, why, **more)
        if act.wild and kind not in NEVER_KINDS:
            content = what in ("read", "search", "zip", "copy") or act.write or kind in ("change", "overwrite", "delete")
            for glob in act.globs:
                refused = self.blocked_glob(glob, act.write or kind in ("change", "overwrite", "delete"),
                                            content and act.recurse, content)
                if refused:
                    act = Act(refused, refused, f"{why}, whose pattern {glob} reaches a protected place",
                              paths=[glob])
                    break
        self.acts.append(act)
        return act

    def blocked_glob(self, pattern: str, write: bool, deep: bool, content: bool) -> str:
        """Why a wildcard may never be used ("secrets", "system"), or "": what it could match is held against the
        protected places, as read.py does for PowerShell, and what it matches now is checked one by one."""
        p = [c for c in pattern.split("/") if c]
        home = [c for c in self.home.split("/") if c]
        if len(p) > len(home) and _reaches(p, home, False):
            entry = p[len(home)]
            inside = len(p) > len(home) + 1
            if (entry.startswith((".", "[")) and (inside or content)) or (
                    fnmatch.fnmatchcase("Library", entry) and (inside or deep)):
                return "secrets"
        if len(p) >= 3 and p[0] == "proc" and (len(p) > 3 or content) and any(
                fnmatch.fnmatchcase(x, p[2]) for x in ("environ", "mem", "maps", "cmdline", "root", "cwd", "fd")):
            return "secrets"
        for root in SECRET_PLACES:
            if _reaches(p, [c for c in root.split("/") if c], deep):
                return "secrets"
        if deep and len(p) <= len(home) and _reaches(p, home, True):
            return "secrets"
        if write and not any(_under(re.split(r"[*?\[]", pattern)[0], t) for t in TEMP_PLACES):
            for root in SYSTEM_PLACES:
                if _reaches(p, [c for c in root.split("/") if c], False):
                    return "system"
        for place in globlib.glob(pattern)[:5000]:
            refused = self.blocked_place(place, write, deep)
            if refused:
                return refused
        return ""

    def resolve(self, text: str) -> str | None:
        """The absolute place a path names, or None when the folder it is relative to is not known."""
        if not text.startswith("/"):
            if self.cwd is None:
                return None
            text = posixpath.join(self.cwd, text)
        return "/" + posixpath.normpath(text).lstrip("/")

    def blocked(self, path: str, write: bool, deep: bool = False) -> str:
        """Why a command may never touch this place ("secrets", "system"), or "". `deep`: everything under it is
        read or changed, so a protected place inside counts too."""
        if re.search(r"[*?\[]", path):
            return self.blocked_glob(path, write, deep, True)
        return self.blocked_place(path, write, deep)

    def blocked_place(self, path: str, write: bool, deep: bool) -> str:
        if NOT_FILES.match(path):
            # /dev/null, /dev/stdout and a pipe's /dev/fd/N (on Linux links into /proc/self/fd) hold no file.
            return ""
        for place in dict.fromkeys((path, posixpath.realpath(path))):
            name = posixpath.basename(place).lower()
            if (name in SECRET_NAMES or name.startswith((".env", "id_rsa", "id_ed25519", "id_ecdsa"))
                    or name.endswith(SECRET_SUFFIXES)):
                return "secrets"
            if _under(place, self.home) and place != self.home:
                rest = place[len(self.home):].lstrip("/")
                if rest.startswith((".", "Library/")) or rest == "Library":
                    return "secrets"
            if any(_under(place, s) for s in SECRET_PLACES) or SECRET_PATTERNS.match(place):
                return "secrets"
            if _under(place, "/dev") and not NOT_FILES.match(place) and not place.startswith(("/dev/shm", "/dev/fd")):
                return "system"
            if deep and (_under(self.home, place) or any(_under(s, place) for s in SECRET_PLACES)):
                return "secrets"
            if write and not any(_under(place, t) for t in TEMP_PLACES) and (
                    any(_under(place, s) for s in SYSTEM_PLACES) or place == "/"
                    or (posixpath.dirname(place) == "/" and place not in OWN_TOPS)):
                return "system"
        return ""

    def touch(self, kind: str, what: str, why: str, paths: list[str], write: bool = False, recurse: bool = False,
              **more) -> Act:
        """An act on these places, or a never act when one of them is protected."""
        content = what in ("read", "search", "zip", "copy") or write
        for path in paths:
            refused = self.blocked(path, write, deep=recurse and content)
            if refused:
                reach = "" if why.endswith(path) else f", which reaches {path}"
                return self.add(refused, refused, f"{why}{reach}, which is protected", paths=[path])
        return self.add(kind, what, why, paths=paths, write=write, recurse=recurse, **more)

    # ------------------------------------------------------------ words

    def word(self, node) -> Word | None:
        """What one argument stands for after quotes and expansions, or None when it is computed as it runs."""
        kind = node.type
        if kind == "word":
            raw = _text(node)
            if BRACES.search(raw):
                return None
            wild = bool(re.search(r"(?<!\\)[*?\[]", raw))
            if raw.startswith("~"):
                head = raw.partition("/")[0]
                if head != "~":
                    return None
                raw = self.home + raw[1:]
            return Word(re.sub(r"\\(.)", r"\1", raw), wild)
        if kind == "number":
            return Word(_text(node))
        if kind == "raw_string":
            return Word(_text(node)[1:-1])
        if kind == "ansi_c_string":
            body = _text(node)[2:-1]
            return None if "\\" in body else Word(body)
        if kind in ("string", "translated_string"):
            out = ""
            for child in node.named_children:
                if child.type == "string_content":
                    out += re.sub(r"\\([$`\"\\\n])", r"\1", _text(child))
                else:
                    got = self.word(child)
                    if got is None:
                        return None
                    out += got.text
            return Word(out)
        if kind in ("simple_expansion", "expansion"):
            names = [c for c in node.named_children if c.type == "variable_name"]
            plain = all(c.is_named or c.type in ("$", "${", "}") for c in node.children)
            if len(node.named_children) != 1 or not names or not plain:
                return None
            value = self.variable(_text(names[0]))
            quoted = node.parent is not None and node.parent.type == "string"
            if value is None or (not quoted and re.search(r"\s", value)):
                return None
            return Word(value, not quoted and bool(re.search(r"[*?\[]", value)))
        if kind == "concatenation":
            if BRACES.search(_text(node)):
                return None
            parts = [self.word(c) for c in node.named_children]
            if any(p is None for p in parts):
                return None
            return Word("".join(p.text for p in parts), any(p.wild for p in parts))
        if kind == "process_substitution":
            # <(...) and >(...) stand for a pipe the shell names under /dev/fd; what runs inside is sorted by nested.
            return Word(PIPE)
        return None

    def variable(self, name: str) -> str | None:
        if name in self.consts:
            return self.consts[name]
        if name == "HOME":
            return self.home
        if name == "PWD":
            return self.cwd
        return None

    def nested(self, node) -> None:
        """Commands run inside an argument (command and process substitution, here-document bodies), and
        arithmetic that evaluates a variable which may hold code."""
        stack = [node]
        while stack:
            item = stack.pop()
            if item.type in ("command_substitution", "process_substitution"):
                saved = self.cwd
                for child in item.named_children:
                    self.statement(child)
                self.cwd = saved
                continue
            if item.type in ("arithmetic_expansion", "subscript"):
                self.arithmetic(item)
            stack.extend(item.children)

    def arithmetic(self, node) -> None:
        names = set()
        stack = [node]
        while stack:
            item = stack.pop()
            if item.type == "variable_name" or (item.type == "word" and re.fullmatch(r"[A-Za-z_]\w*", _text(item))):
                names.add(_text(item))
            stack.extend(item.children)
        for name in sorted(names & self.unsafe)[:1]:
            self.add("hidden", "hidden", f"evaluates ${name} as arithmetic, which runs any command written in it")

    # ------------------------------------------------------------ statements

    def statement(self, node, upstream: list[Act] | None = None) -> None:
        kind = node.type
        if kind == "&":
            self.add("hidden", "hidden", "leaves a command running in the background, out of sight")
        elif kind == "command":
            self.command(node, upstream, [])
        elif kind == "redirected_statement":
            body = node.child_by_field_name("body")
            rest = [c for c in node.named_children if c != body]
            if body is not None and body.type == "command":
                self.command(body, upstream, rest)
                return
            if body is not None:
                self.statement(body, upstream)
            for redirect in rest:
                self.redirect(redirect, {"kind": "", "text": None, "start": len(self.acts)})
        elif kind == "pipeline":
            saved, before = self.cwd, len(self.acts)
            stages = node.named_children
            for n, stage in enumerate(stages):
                self.statement(stage, self.acts[before:] if n else upstream)
                if len(stages) > 1:
                    self.cwd = saved
        elif kind in ("variable_assignment", "variable_assignments"):
            for one in ([node] if kind == "variable_assignment" else node.named_children):
                self.assign(one, keep=True)
        elif kind == "declaration_command":
            self.declaration(node)
        elif kind == "unset_command":
            for child in node.named_children:
                self.consts.pop(_text(child), None)
        elif kind == "function_definition":
            name = node.child_by_field_name("name")
            if name is not None and _text(name) in ("command_not_found_handle", "command_not_found_handler"):
                self.add("hidden", "hidden", "defines what runs for every unknown command")
            if name is not None and node.parent is not None and node.parent.type == "program":
                self.funcs.add(_text(name))
            saved = self.cwd
            body = node.child_by_field_name("body")
            if body is not None:
                self.statement(body)
            if self.cwd != saved:
                # Where a call of it leaves the command is known only as it runs.
                self.cwd = None
        elif kind == "test_command":
            self.nested(node)
            if node.children and node.children[0].type == "[[" and re.search(r"\s-(eq|ne|lt|le|gt|ge)\s",
                                                                             _text(node)):
                self.arithmetic(node)
        elif kind == "compound_statement" and node.children and node.children[0].type == "((":
            self.nested(node)
            self.arithmetic(node)
        elif kind == "c_style_for_statement":
            for child in node.named_children:
                if child.type in ("do_group", "compound_statement"):
                    self.statement(child)
                else:
                    self.nested(child)
        elif kind in ("program", "list", "compound_statement", "subshell", "do_group", "negated_command",
                      "if_statement", "elif_clause", "else_clause", "while_statement", "for_statement",
                      "case_statement", "case_item"):
            saved = self.cwd
            words = ("word", "string", "raw_string", "concatenation", "simple_expansion", "expansion", "number",
                     "extglob_pattern", "variable_name", "command_substitution", "arithmetic_expansion",
                     "ansi_c_string", "regex", "brace_expression", "process_substitution")
            either = kind == "list" and any(c.type == "||" for c in node.children)
            if kind in ("while_statement", "for_statement") and any(
                    c.type == "command_name" and _text(c) in ("cd", "pushd", "popd") for c in _descendants(node)):
                # A loop that changes folder runs its next pass from wherever the last one ended.
                self.cwd = None
            for child in node.children:
                before = self.cwd
                if child.type in words:
                    self.nested(child)
                elif child.is_named or child.type == "&":
                    self.statement(child)
                # A cd that may fail leaves what follows in either folder; only `cd x && ...` is sure of x.
                if self.cwd not in (before, None) and kind != "list" and not os.path.isdir(self.cwd) or (
                        either and self.cwd != before):
                    self.cwd = None
            if kind == "subshell":
                self.cwd = saved
            elif kind in ("if_statement", "elif_clause", "else_clause", "case_statement", "case_item",
                          "while_statement", "for_statement") and self.cwd != saved:
                self.cwd = None
        elif kind in ("file_redirect", "heredoc_redirect", "herestring_redirect"):
            self.redirect(node, {"kind": "", "text": None, "start": len(self.acts)})
        elif kind != "comment":
            self.add("unknown", "unknown", f"uses {kind.replace('_', ' ')}, which the app does not read")

    def assign(self, node, keep: bool) -> None:
        """One NAME=value: its value's own commands; a variable that changes what runs is hidden."""
        name_node, value = node.child_by_field_name("name"), node.child_by_field_name("value")
        name = _text(name_node) if name_node is not None else ""
        if value is not None:
            self.nested(value)
        if DANGEROUS_VARS.match(name) and not (name == "IFS" and not keep):
            self.add("hidden", "redefine", f"sets {name}, which changes what later commands run or load")
            return
        got = self.word(value) if keep and value is not None and name in self.once else None
        if got is not None:
            self.consts[name] = got.text
        else:
            self.consts.pop(name, None)

    def declaration(self, node) -> None:
        flags = "".join(_text(c)[1:] for c in node.children if c.type == "word" and _text(c).startswith("-"))
        if node.children and node.children[0].type == "export" and "f" in flags:
            self.add("hidden", "redefine", "exports a function to every program it starts")
        if "n" in flags:
            self.add("hidden", "redefine", "makes one variable's name stand for another's")
        for child in node.named_children:
            if child.type == "variable_assignment":
                self.assign(child, keep=True)
            elif child.type == "variable_name" and DANGEROUS_VARS.match(_text(child)):
                self.add("hidden", "redefine", f"exports {_text(child)}, which changes what later commands run")
            else:
                self.nested(child)

    # ------------------------------------------------------------ redirections

    def redirect(self, node, stdin: dict) -> None:
        """One redirection: a file written or read, a connection opened, or what a command reads on its input
        (here-document, here-string, file), noted in `stdin`."""
        if node.type == "herestring_redirect":
            for child in node.named_children:
                self.nested(child)
                got = self.word(child)
                stdin.update(kind="text", text=got.text if got is not None else None)
            return
        if node.type == "heredoc_redirect":
            start = next((c for c in node.named_children if c.type == "heredoc_start"), None)
            quoted = start is not None and bool(re.search(r"[\"'\\]", _text(start)))
            body = next((c for c in node.named_children if c.type == "heredoc_body"), None)
            expands = body is not None and any(c.type != "heredoc_content" for c in body.named_children)
            if body is not None and not quoted:
                self.nested(body)
            stdin.update(kind="text", text=None if expands and not quoted else (_text(body) if body else ""))
            for child in node.named_children:
                if child.type in ("file_redirect", "herestring_redirect"):
                    self.redirect(child, stdin)
                elif child.type not in ("heredoc_start", "heredoc_body", "heredoc_end"):
                    # The rest of a pipeline the here-document's command starts (cat <<EOF | sh).
                    self.statement(child, self.acts[stdin["start"]:])
            return
        op = next((_text(c) for c in node.children if not c.is_named), "")
        dest = node.child_by_field_name("destination") or (node.named_children[-1] if node.named_children else None)
        if dest is None or dest.type == "file_descriptor" or op in ("<&-", ">&-"):
            return
        self.nested(dest)
        if dest.type == "process_substitution" or (dest.type == "number" and op in (">&", "<&")):
            return
        got = self.word(dest)
        reading = op in ("<", "<&")
        if got is None or got.wild:
            if reading:
                self.add("read", "read", "reads a file whose name is computed", unresolved=True)
            else:
                self.add("unknown", "write", "writes its output to a file whose name is computed", unresolved=True,
                         write=True)
            return
        if reading:
            stdin.update(kind="file", text=None)
        if NOT_FILES.match(got.text):
            return
        net = re.match(r"^/dev/(tcp|udp)/([^/]+)/(\d+)", got.text)
        if net:
            self.reach(net.group(2), True, f"opens a connection to {net.group(2)} through /dev/{net.group(1)}")
            return
        place = self.resolve(got.text)
        if place is None:
            self.add("unknown", "write", f"uses {got.text} in a folder known only as it runs", unresolved=True,
                     write=not reading)
        elif reading:
            self.touch("read", "read", f"reads {place}", [place], globs=[place])
        else:
            append = ">>" in op
            self.touch("overwrite" if os.path.isfile(place) and not append else "change",
                       "append" if append else "write", f"{'appends' if append else 'writes'} its output to {place}",
                       [place], write=True)

    def reach(self, host: str, sends: bool, why: str, **more) -> None:
        host = host.lower().strip("[]")
        if host and host != "?" and _local_host(host):
            self.add("system", "loopback", f"reaches this computer's own services at {host}")
            return
        self.add("network", "net", why, host=host or "?", sends=sends, **more)

    # ------------------------------------------------------------ one command

    def command(self, node, upstream: list[Act] | None, redirects: list) -> None:
        stdin = {"kind": "pipe" if upstream is not None else "", "text": None, "start": len(self.acts)}
        name_node = node.child_by_field_name("name")
        words: list[Word | None] = []
        for child in node.named_children:
            if child.type == "variable_assignment":
                self.assign(child, keep=False)
            elif child.type in ("file_redirect", "heredoc_redirect", "herestring_redirect"):
                redirects = [*redirects, child]
            elif child != name_node:
                self.nested(child)
                words.append(self.word(child))
        for redirect in redirects:
            self.redirect(redirect, stdin)
        if name_node is None:
            return
        self.nested(name_node)
        head = name_node.named_children[0] if name_node.named_children else None
        named = self.word(head) if head is not None else None
        # A name pieced together from quotes or set by a variable in the command hides what runs, as read.py
        # takes `& $c`; only $HOME and $PWD, which the command does not set, may stand in a program's path.
        pieced = head is not None and head.type == "concatenation" and any(
            c.type in ("string", "raw_string", "ansi_c_string") for c in head.named_children)
        named_by = [_text(c) for c in _descendants(head) if c.type == "variable_name"] if head is not None else []
        if named is None or named.wild or pieced or any(n not in ("HOME", "PWD") or n in self.consts
                                                         for n in named_by):
            self.add("hidden", "hidden", f"runs a command whose name is computed ({_text(name_node)[:60]}), "
                                         "which cannot be read first")
            return
        if named.text in self.funcs:
            return
        self.run(named.text, words, upstream or [], stdin)

    def args(self, words: list[Word | None], values: str = "", files: str = "") -> tuple[list, list]:
        """(flags, positional words) of a command's arguments. A short option in `values` takes the next word,
        which is not positional, unless the option is in `files` (grep -f FILE): then that word is a file read."""
        flags, positional, take, ended = [], [], "", False
        for word in words:
            if take:
                if take in files:
                    positional.append(word)
                take = ""
                continue
            if word is None:
                positional.append(None)
                continue
            text = word.text
            if not ended and text == "--":
                ended = True
            elif not ended and text.startswith("-") and len(text) > 1:
                flags.append(text)
                if re.fullmatch(r"-[A-Za-z0-9]+", text) and text[-1] in values:
                    take = text[-1]
                elif "=" in text or text[2:3] in ("/", "~", "."):
                    # A value given in the same word (--file=x, -f/x) may be a place.
                    value = text.split("=", 1)[1] if "=" in text else text[2:]
                    if value.startswith(("/", "~/", "./", "../")):
                        positional.append(Word(self.home + value[1:] if value.startswith("~/") else value))
            else:
                positional.append(word)
        return flags, positional

    def places(self, words: list) -> tuple[list[str], list[str], bool, bool]:
        """(absolute places, the patterns among them, any pattern, any computed) of positional words. A pattern's
        place is the folder before its first wildcard."""
        out, globs, wild, unresolved = [], [], False, False
        for word in words:
            place = self.resolve(word.text) if word is not None else None
            if place is None:
                unresolved = True
                continue
            if word.wild:
                wild = True
                globs.append(place)
                base = re.split(r"[*?\[]", place)[0]
                place = (base if base.endswith("/") else posixpath.dirname(base)).rstrip("/") or "/"
            out.append(place)
        return out, globs, wild, unresolved

    def run(self, name: str, words: list[Word | None], upstream: list[Act], stdin: dict) -> None:
        """Sorts one command by its name, with its arguments as they will be after expansion."""
        folder, base = posixpath.split(name)
        low = base.lower()
        texts = _texts(words)
        never = NEVER.get(low) or NEVER.get(low.split(".")[0])
        if never:
            self.add(never, never, f"runs {base}")
        elif folder and posixpath.normpath(folder) not in BIN_DIRS:
            self.program(name, words)
        elif low in WRAPPERS:
            self.wrapper(low, words, upstream, stdin)
        elif low in ("alias", "trap"):
            if (low == "alias" and any(t is None or "=" in t for t in texts)) or (
                    low == "trap" and len(texts) >= 2 and texts[0] not in ("-", "-p", "-l")):
                self.add("hidden", "redefine", f"{base} makes later words run something else")
        elif low in ("source", "."):
            self.source(texts)
        elif low in ("cd", "pushd", "popd"):
            self.location(low, texts)
        elif low in SHELLS:
            self.shell(base, words, upstream, stdin)
        elif low in OTHER_SHELLS:
            self.add("hidden", "hidden", f"runs {base}, whose commands this app does not read")
        elif re.fullmatch(r"(python|pypy)[\d.]*w?", low) or low in INTERPRETERS_POSIX:
            self.interpreter("python" if low.startswith(("python", "pypy")) else low, words, upstream, stdin)
        elif low in PURE:
            pass
        elif low in FACTS:
            self.facts(low, texts)
        elif low in SYSTEM_READ:
            self.system_tool(low, texts)
        elif low in READS or low in SEARCHERS:
            self.reads(low, words)
        elif low in ("sed", "gsed"):
            self.sed(words)
        elif low in ("awk", "gawk", "mawk", "nawk"):
            self.awk(words)
        elif low == "find":
            self.find(words)
        elif low == "xargs":
            self.xargs(words)
        elif low in ("cp", "mv", "install", "ditto", "rsync"):
            self.copy(low, words)
        elif low in ("rm", "unlink", "rmdir", "shred", "srm", "trash", "trash-put"):
            self.delete(low, words)
        elif low in ("mkdir", "touch", "truncate", "tee", "chmod", "dd", "mktemp", "split", "csplit", "patch"):
            self.change(low, words)
        elif low in ("tar", "zip", "unzip", "gzip", "gunzip", "bzip2", "bunzip2", "xz", "unxz", "zstd", "unzstd",
                     "lz4", "7z", "7za", "compress", "uncompress"):
            self.archive(low, words)
        elif low in NETWORK:
            self.network(low, words)
        elif low == "git":
            self.git(texts)
        elif low in ("open", "xdg-open", "gio", "gnome-open", "kde-open", "kde-open5", "wslview"):
            self.open(low, texts)
        elif low in ("kill", "pkill", "killall", "xkill", "skill"):
            self.add("program", "stop", f"ends a running program ({_short(texts)[:60]})",
                     name=f"{base} {_short(texts)}")
        elif low in ("pbpaste", "wl-paste", "xclip", "xsel"):
            if low in ("pbpaste", "wl-paste") or any(t in ("-o", "--output", "-out") for t in texts):
                self.add("outside", "clipboard", "reads what is on the clipboard")
        elif low in ("docker", "podman", "nerdctl", "kubectl", "lima", "colima", "vagrant"):
            joined = _short(texts)
            if re.search(r"--privileged|--pid[= ]host|--net(work)?[= ]host|--cap-add|-v\s*/:|--volume[= ]/:|--device",
                         joined):
                self.add("elevate", "elevate", f"runs {base} with the computer's own rights")
            else:
                self.add("program", "program", f"runs {base} {joined[:80]}", name=f"{base} {joined}"[:160])
        elif low in INSTALL or low in ("npx", "pnpx", "bunx", "uvx"):
            self.install(low, texts)
        elif low in PROGRAMS:
            if self.named_places(base, words) is not None:
                self.add("program", "program", f"runs {base} {_short(texts)[:80]}".strip(),
                         name=f"{base} {_short(texts)}", args=[t or "?" for t in texts])
        else:
            self.unknown(base, words)

    # ------------------------------------------------------------ kinds of command

    def program(self, name: str, words: list[Word | None]) -> None:
        place = self.resolve(name)
        if place == PIPE:
            self.add("hidden", "hidden", "runs commands handed over through a pipe, which cannot be read first")
            return
        if place is None:
            self.add("unknown", "program", f"runs {name} from a folder known only as it runs")
            return
        low = place.lower()
        if low.endswith(SCRIPTS) or "." not in posixpath.basename(place):
            refused = self.blocked(place, False)
            if refused:
                self.add(refused, refused, f"runs {place}, which is protected", paths=[place])
                return
        if low.endswith(PACKAGES):
            self.add("install", "install", f"runs the installer {place}", name=place)
        elif low.endswith(SCRIPTS):
            self.add("program", "script", f"runs the script {place}", name=place, paths=[place])
        else:
            texts = [t or "?" for t in _texts(words)]
            self.add("program", "program", f"runs the program {place}", name=f"{place} {' '.join(texts)}"[:160],
                     paths=[place], args=texts)

    def named_places(self, base: str, words: list[Word | None]) -> list[str] | None:
        """Every argument that could be a place, taken as written to; None, with a never act, when one is
        protected."""
        places = []
        for word in words:
            if word is None or "://" in word.text or not re.search(r"/|\.\w{1,5}$|^\.|^~", word.text):
                continue
            place = self.resolve(word.text.split("=", 1)[-1])
            if place is None:
                continue
            refused = self.blocked(place, True)
            if refused:
                self.add(refused, refused, f"runs {base} on {place}, which is protected", paths=[place])
                return None
            places.append(place)
        return places

    def unknown(self, base: str, words: list[Word | None]) -> None:
        """A command the tables do not know: asked, and every argument that could be a place counts as written,
        so a key or a system file named there is still refused."""
        places = self.named_places(base, words)
        if places is not None:
            self.add("unknown", "unknown", f"runs {base}, which the app does not know", paths=places, write=True,
                     name=f"{base} {_short(_texts(words))}"[:160])

    def wrapper(self, low: str, words: list[Word | None], upstream: list[Act], stdin: dict) -> None:
        rest, take = list(words), False
        while rest and rest[0] is not None:
            text = rest[0].text
            if take:
                take = False
            elif low == "env" and re.fullmatch(r"[A-Za-z_]\w*=.*", text, re.DOTALL):
                var = text.split("=", 1)[0]
                if DANGEROUS_VARS.match(var):
                    self.add("hidden", "redefine", f"sets {var}, which changes what the command runs or loads")
                    return
            elif text.startswith("-") and len(text) > 1:
                if low in ("command", "builtin") and text in ("-v", "-V"):
                    return
                if low == "env" and text in ("-S", "--split-string") or text.startswith("-S"):
                    self.add("hidden", "hidden", "env -S splits a string into a command")
                    return
                take = re.fullmatch(r"-[A-Za-z]+", text) is not None and text[-1] in WRAPPERS[low]
            elif not (low in ("timeout", "watch") and re.fullmatch(r"[\d.]+[smhd]?", text)):
                break
            rest.pop(0)
        if not rest:
            if low == "env":
                self.add("read", "info", "lists the environment variables")
            return
        if rest[0] is None:
            self.add("hidden", "hidden", f"{low} runs a command whose name is computed")
            return
        self.run(rest[0].text, rest[1:], upstream, stdin)

    def location(self, low: str, texts: list[str | None]) -> None:
        if low == "popd":
            self.cwd = self.stack.pop() if self.stack else None
            return
        targets = [t for t in texts if t is None or not t.startswith("-") or t == "-"]
        if low == "pushd":
            self.stack.append(self.cwd)
        if not targets:
            if low == "cd":
                self.cwd = self.home
            return
        place = self.resolve(targets[0]) if targets[0] not in (None, "-") else None
        self.cwd = place
        if place is not None:
            self.touch("read", "look", f"works in {place}", [place])

    def source(self, texts: list[str | None]) -> None:
        place = self.resolve(texts[0]) if texts and texts[0] is not None else None
        if place in (None, PIPE):
            self.add("hidden", "hidden", "runs commands read from a place computed as it runs")
            return
        refused = self.blocked(place, False)
        if refused:
            self.add(refused, refused, f"runs commands from {place}, which is protected", paths=[place])
            return
        self.add("program", "script", f"runs the commands in {place}", name=place, paths=[place])

    @staticmethod
    def fed(upstream: list[Act], stdin: dict) -> str:
        """Where a shell or an interpreter reads its code from: "fetched" (the network or a decoder upstream),
        "pipe", "text" (a here-document or here-string), "file", or ""."""
        if any(a.kind == "network" or a.what == "decode" for a in upstream):
            return "fetched"
        return stdin.get("kind") or ""

    def shell(self, base: str, words: list[Word | None], upstream: list[Act], stdin: dict) -> None:
        texts = _texts(words)
        code_at = next((n for n, t in enumerate(texts) if t is not None and (t == "-c" or _bundles(t, "c"))), None)
        if code_at is not None:
            if code_at + 1 >= len(words) or words[code_at + 1] is None:
                self.add("hidden", "hidden", f"runs {base} -c with code computed as it runs")
            else:
                self.inner(words[code_at + 1].text, base)
            return
        source = self.fed(upstream, stdin)
        if source == "fetched":
            self.add("hidden", "download_run", f"runs what the network or a decoder hands to {base}")
            return
        script = next((t for t in texts if t is None or not t.startswith("-")), "")
        if script == PIPE:
            self.add("hidden", "hidden", f"runs commands handed to {base} through a pipe, which cannot be read first")
        elif script:
            place = self.resolve(script)
            refused = self.blocked(place, False) if place else ""
            if refused:
                self.add(refused, refused, f"runs {place} with {base}, which is protected", paths=[place])
            else:
                self.add("program", "script", f"runs {script} with {base}", name=f"{base} {_short(texts)}",
                         paths=[place] if place else [], unresolved=place is None)
        elif script is None:
            self.add("hidden", "hidden", f"runs {base} on a script whose name is computed")
        elif source == "text" and stdin.get("text") is not None:
            self.inner(stdin["text"], base)
        else:
            self.add("hidden", "hidden", f"runs commands given to {base} on its input, which cannot be read first")

    def inner(self, code: str, base: str) -> None:
        """`bash -c '...'` and a here-document into bash: the code is read as a command of its own."""
        if self.depth >= DEPTH_MAX:
            self.add("hidden", "hidden", f"runs {base} inside {base} too deeply to read")
            return
        root = _tree(code)
        if root.has_error:
            self.add("unknown", "unknown", f"gives {base} code that does not parse")
            return
        sub = Sorter(self.cwd, self.home, self.depth + 1)
        sub.survey(root)
        sub.statement(root)
        self.acts += sub.acts

    def interpreter(self, low: str, words: list[Word | None], upstream: list[Act], stdin: dict) -> None:
        texts = _texts(words)
        letters = INLINE.get(low, "e")
        if (texts and texts[0] is None) or any(t is not None and (_bundles(t, letters) or t in INLINE_LONG or any(
                t.startswith(f"{x}=") for x in INLINE_LONG)) for t in texts):
            self.add("hidden", "hidden", f"runs {low} with code given on the command line")
            return
        lowered = [t.lower() for t in texts if t is not None]
        if lowered[:2] == ["-m", "pip"]:
            self.pip(lowered[2:])
            return
        if lowered[:1] in (["--version"], ["-v"], ["-version"], ["--help"], ["-h"]):
            self.add("read", "info", f"asks {low} its version")
            return
        source = self.fed(upstream, stdin)
        if source == "fetched":
            self.add("hidden", "download_run", f"runs what the network or a decoder hands to {low}")
            return
        script = next((t for t in texts if t is None or not t.startswith("-")), "")
        if script is None or script == PIPE:
            self.add("hidden", "hidden", f"runs {low} on a script whose name is computed")
            return
        place = self.resolve(script) if script and lowered[:1] != ["-m"] else None
        refused = self.blocked(place, False) if place else ""
        if refused:
            self.add(refused, refused, f"runs {place}, which is protected", paths=[place])
            return
        self.add("program", "script", f"runs {low} {_short(texts)[:80]}".strip() + (
            "" if script else " with code given on its input"), name=f"{low} {_short(texts)}"[:160],
            paths=[place] if place else [])

    def pip(self, words: list[str]) -> None:
        if words and words[0] in ("list", "show", "freeze", "check", "--version", "-v", "inspect"):
            self.add("read", "apps", "lists what pip installed")
        elif words and words[0] in ("search", "index", "download"):
            self.add("network", "net", f"runs pip {' '.join(words)[:60]}", host="pypi.org", sends=False)
        else:
            self.add("install", "install", f"runs pip {' '.join(words)[:80]}", name=f"pip {' '.join(words)}"[:120])

    def install(self, low: str, texts: list[str | None]) -> None:
        words = [t for t in texts if t is not None]
        first = next((t for t in words if not t.startswith("-") or t in INSTALL_READ or t in INSTALL_SEARCH), "")
        said = " ".join(words)
        if low in DOWNLOAD_RUN or f"{low} {first}" in DOWNLOAD_RUN:
            self.add("hidden", "download_run", f"{low} downloads a package and runs it")
        elif low in ("pip", "pip3") or (low == "uv" and first == "pip"):
            self.pip(words[1:] if low == "uv" else words)
        elif low == "brew" and first == "services":
            self.add("system", "system", "changes background services with brew")
        elif first in BUILD_WORDS and low not in ("apt", "apt-get", "brew", "dnf", "yum", "pacman", "snap"):
            self.add("program", "program", f"runs {low} {said[:80]}", name=f"{low} {said}"[:160])
        elif first in INSTALL_READ or (not words and low in ("brew", "apt", "go", "cargo")):
            self.add("read", "apps", f"lists what {low} installed")
        elif first in INSTALL_SEARCH or (low == "softwareupdate" and first in ("-l", "--list")):
            self.add("network", "net", f"searches the {low} catalogue online", host=low, sends=False)
        else:
            self.add("install", "install", f"runs {low} {said[:80]}", name=f"{low} {said}"[:120])

    def facts(self, low: str, texts: list[str | None]) -> None:
        if low == "nvidia-smi" and any(t is None or (t.startswith("-") and not t.startswith(
                ("-q", "--query", "-L", "--list", "--format", "-i", "--id", "-d", "--display", "-h", "--help", "-l")))
                for t in texts):
            self.add("system", "system", "changes the graphics card's settings with nvidia-smi")
        else:
            self.add("read", FACTS[low], f"reads {low}")

    def system_tool(self, low: str, texts: list[str | None]) -> None:
        """A system tool that reads with some words and changes the system with the rest."""
        allowed = SYSTEM_READ[low]
        if any(t is None for t in texts):
            self.add("system", "system", f"runs {low} with computed arguments")
            return
        words = list(texts)
        if not words:
            changes = low not in SYSTEM_BARE
        elif low == "date":
            changes = any(w in ("-s", "--set") or re.fullmatch(r"\d{4,12}(\.\d\d)?", w) for w in words)
        elif low == "hostname":
            changes = any(w not in allowed for w in words)
        elif low == "ifconfig":
            changes = len([w for w in words if not w.startswith("-")]) > 1
        elif low == "networksetup":
            changes = not all(w.startswith(("-get", "-list", "-print", "-version", "-help")) or not w.startswith("-")
                              for w in words)
        elif low in ("ip", "nmcli"):
            changes = bool(set(words) & SYSTEM_VERBS) or words[0] not in allowed
        elif low == "sysctl":
            changes = any("=" in w for w in words) or any(w.startswith("-") and w not in allowed for w in words)
        elif low in ("mount", "xattr"):
            changes = any(w.startswith("-") and w not in allowed for w in words) or (
                low == "mount" and any(not w.startswith("-") for w in words))
        else:
            changes = words[0] not in allowed
        if low in ("systemctl", "launchctl") and words and words[0] in ("poweroff", "reboot", "halt", "suspend",
                                                                        "hibernate", "kexec", "soft-reboot"):
            self.add("shutdown", "shutdown", f"runs {low} {words[0]}")
        elif changes:
            self.add("system", "system", f"runs {' '.join([low, *words])[:80]}, which changes the system")
        else:
            self.add("read", "info", f"reads {' '.join([low, *words])[:80]}")

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
                before = len(self.acts)
                self.run(sub[0].text, sub[1:], [], {"kind": "", "text": None})
                ran, self.acts = self.acts[before:], self.acts[:before]
                for act in ran:
                    if act.kind not in ("read", "change", "overwrite", "delete") or act.paths:
                        self.acts.append(act)
                        continue
                    # What it runs on is each file found: any place under the folders searched. A read of them
                    # is as known as the folders are; a change or delete is known only as it runs.
                    self.touch(act.kind, act.what, act.why.replace("places computed as it runs", _some(places)),
                               list(places), write=act.write, recurse=True, wild=True,
                               unresolved=unresolved or act.kind != "read", globs=list(places))
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
        for place in sources:
            refused = self.blocked(place, what == "move", deep=recurse)
            if refused:
                self.add(refused, refused, f"{VERBED.get(what, what)} {place}, which is protected", paths=[place])
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
            flags, positional = self.args(words, "xib")
            if not positional:
                return
            recurse = any(_bundles(f, "r") for f in flags)
            sources, globs, wild, unresolved = self.places(positional[1:])
            for place in sources:
                refused = self.blocked(place, False, deep=recurse)
                if refused:
                    self.add(refused, refused, f"zips {place}, which is protected", paths=[place])
                    return
            if sources:
                self.add("read", "read", f"reads {_some(sources)}", paths=sources, wild=wild, globs=globs or sources,
                         recurse=recurse, unresolved=unresolved)
            self.write_to(positional[0].text, "zip writes", what="zip")
        elif low == "unzip":
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

    def tar(self, texts: list[str]) -> None:
        if texts and re.fullmatch(r"[A-Za-z]+", texts[0]):
            texts = ["-" + texts[0]] + texts[1:]
        mode, archive, dest, sources, n = "", None, None, [], 0
        longs = {"--create": "c", "--extract": "x", "--get": "x", "--list": "t", "--append": "r", "--update": "u",
                 "--delete": "x"}
        while n < len(texts):
            t = texts[n]
            if t.startswith(("--to-command", "--use-compress-program", "--checkpoint-action", "--info-script",
                             "--new-volume-script", "-I", "--rsh-command", "--rmt-command", "-F")):
                self.add("hidden", "hidden", "tar runs a program it is given")
                return
            if t in longs:
                mode += longs[t]
            elif t.startswith("--file="):
                archive = t.split("=", 1)[1]
            elif t in ("-C", "--directory", "-f", "--file") and n + 1 < len(texts):
                if t in ("-C", "--directory"):
                    dest = texts[n + 1]
                else:
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
        if set(mode) & set("cru"):
            places, globs, wild, unresolved = self.places([Word(s) for s in sources])
            for place in places:
                refused = self.blocked(place, False, deep=True)
                if refused:
                    self.add(refused, refused, f"archives {place}, which is protected", paths=[place])
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

    def network(self, low: str, words: list[Word | None]) -> None:
        texts = _texts(words)
        if low in ("curl", "wget", "http", "https", "xh", "aria2c", "axel"):
            self.fetch(low, texts)
            return
        if any(t is None for t in texts):
            self.reach("?", True, f"runs {low} with computed arguments")
            return
        _, positional = self.args(words, NET_VALUES.get(low, ""))
        hosts = [p.text.split("@")[-1] for p in positional if not p.text.startswith("@")
                 and (re.search(r"[.:]", p.text) or p.text.lower() == "localhost" or "://" in p.text)]
        host = (urlsplit(hosts[0]).hostname or hosts[0]) if hosts and "://" in hosts[0] else (hosts[0] if hosts else "")
        sends = low in ("nc", "ncat", "netcat", "socat", "ftp", "tftp", "lftp")
        self.reach(host, sends, f"runs {low} to reach {host or 'the network'}", name=f"{low} {_short(texts)}"[:120])

    def fetch(self, low: str, texts: list[str | None]) -> None:
        """curl, wget and their kind: the addresses reached, what is sent, the files read to send and written."""
        if any(t is None for t in texts):
            self.reach("?", True, f"runs {low} with computed arguments")
            return
        shorts = CURL_VALUES if low == "curl" else WGET_VALUES if low == "wget" else ("-o", "-d", "-P")
        pairs, urls, n = [], [], 0
        while n < len(texts):
            t = texts[n]
            nxt = texts[n + 1] if n + 1 < len(texts) else ""
            if t.startswith("--"):
                key, eq, value = t.partition("=")
                if eq:
                    pairs.append((key, value))
                elif key in FETCH_LONG:
                    pairs.append((key, nxt))
                    n += 1
                else:
                    pairs.append((key, ""))
            elif t.startswith("-") and len(t) > 1:
                for i, c in enumerate(t[1:], 1):
                    if f"-{c}" in shorts:
                        value = t[i + 1:] or nxt
                        pairs.append((f"-{c}", value))
                        n += 0 if t[i + 1:] else 1
                        break
                    pairs.append((f"-{c}", ""))
            elif low in ("http", "https", "xh") and urls:
                pairs.append(("item", t))
            else:
                urls.append(t)
            n += 1
        outs, reads, sends = [], [], False
        for key, value in pairs:
            if key in FETCH_OUT and value != "-" and not (low == "curl" and key == "-c" and not value):
                outs.append(value)
            elif (key in ("-P", "--directory-prefix", "--dir", "-d") and low != "curl") or key == "--output-dir":
                outs.append(posixpath.join(value, "*"))
            elif key in ("-O", "--remote-name", "--remote-name-all") and low == "curl":
                outs.append("*")
            elif key == "-O" and low == "wget" and value != "-":
                outs.append(value)
            elif key == "--url":
                urls.append(value)
            elif key == "item":
                sends = sends or bool(re.search(r"[=:@]", value)) or value.upper() in ("POST", "PUT", "PATCH",
                                                                                         "DELETE")
            if key in FETCH_IN:
                reads.append(value)
            if key in FETCH_SENDS or (key in ("-X", "--request", "--method") and value.upper() not in ("GET", "HEAD")):
                sends = True
                at = value.split("@", 1)[1] if "@" in value and key not in ("--data-raw", "-u", "--user") else ""
                if at and at != "-" and key not in ("-H", "--header", "-A", "--user-agent", "-e", "--referer"):
                    reads.append(at.split(";")[0])
            if key in ("-K", "--config", "-e", "--execute") and low in ("curl", "wget") and (
                    key != "-e" or low == "wget"):
                self.add("unknown", "unknown", f"{low} takes more options from {value or 'a file'}")
        if low in ("wget", "aria2c", "axel") and not outs and not any(
                k in ("--spider", "-O") or (k == "-O" and v == "-") for k, v in pairs):
            outs.append("*")
        if low == "wget" and any(k == "-O" and v == "-" for k, v in pairs):
            outs = [o for o in outs if o != "*"]
        for raw in reads:
            place = self.resolve(raw) if raw else None
            if place is None:
                self.add("read", "read", f"{low} reads a file to send whose name is computed", unresolved=True)
            else:
                self.touch("read", "read", f"reads {place} to send", [place])
        hosts = []
        for url in urls:
            parts = urlsplit(url if re.match(r"^[a-z][\w+.-]*://", url, re.IGNORECASE) else "http://" + url)
            scheme = parts.scheme.lower()
            if scheme == "file":
                self.touch("read", "read", f"reads {parts.path or '/'}", [parts.path or "/"])
            elif scheme in ("http", "https", "ftp", "ftps", "sftp", "scp", "ws", "wss", "tftp"):
                hosts.append(((parts.hostname or "").lower(), bool(parts.query)))
            else:
                self.add("unknown", "unknown", f"{low} reaches {url[:60]}, a kind of address the app does not know")
        paths = []
        for raw in outs:
            place = self.resolve(raw.replace("*", "") or ".") if raw else None
            if place is None:
                self.add("unknown", "write", f"{low} saves a download under a computed name", unresolved=True,
                         write=True)
                continue
            refused = self.blocked(place, True)
            if refused:
                self.add(refused, refused, f"{low} saves a download to {place}, which is protected", paths=[place])
                return
            paths.append(place)
        for host, query in hosts or [("", True)]:
            self.reach(host, sends or query, f"runs {low} to reach {host or 'the network'}" + (
                " and sends data" if sends or query else ""), paths=paths, write=bool(paths),
                name=f"{low} {' '.join(texts)}"[:120])

    def git(self, texts: list[str | None]) -> None:
        if any(t is None for t in texts):
            self.add("unknown", "unknown", "runs git with computed arguments")
            return
        lowered = [t.lower() for t in texts]
        if any(t in ("-c", "--config-env", "--exec-path") or t.startswith(("--upload-pack", "--receive-pack",
                                                                            "--exec=", "--config-env="))
               for t in lowered):
            self.add("hidden", "hidden", "runs git with settings given on the command line, which can run programs")
        elif set(lowered) & GIT_NET or any("://" in t or t.startswith("--remote") for t in lowered):
            self.add("network", "net", f"runs git {' '.join(texts)[:80]}", host="git", sends="push" in lowered,
                     name=f"git {' '.join(texts)}"[:120])
        else:
            # Local git still runs the repository's own hooks and filters: a program run, as read.py has it.
            self.add("program", "program", f"runs git {' '.join(texts)[:80]}", name=f"git {' '.join(texts)}"[:160],
                     args=list(texts))

    def open(self, low: str, texts: list[str | None]) -> None:
        if any(t is None for t in texts):
            self.add("unknown", "program", f"{low} opens something whose name is computed")
            return
        if low == "gio" and texts[:1] != ["open"]:
            self.add("unknown", "unknown", f"runs gio {' '.join(texts)[:60]}")
            return
        if any(t in ("-a", "-b", "--args", "-e", "-t") for t in texts):
            self.add("program", "program", f"opens a program: {' '.join(texts)[:100]}", name=" ".join(texts)[:160])
            return
        for target in [t for t in texts[1 if low == "gio" else 0:] if not t.startswith("-")]:
            scheme = re.match(r"^([a-z][a-z0-9+.-]+):", target, re.IGNORECASE)
            if scheme and scheme.group(1).lower() in ("http", "https"):
                host = (urlsplit(target).hostname or "").lower()
                if host and _local_host(host):
                    self.add("system", "loopback", f"opens this computer's own services at {host}")
                else:
                    self.add("network", "browse", f"opens {target[:120]} in the browser", host=host or target[:40],
                             sends=True)
                continue
            if scheme:
                self.add("program", "program", f"{low} opens {target[:120]}", name=target[:160])
                continue
            place = self.resolve(target)
            if place is None:
                self.add("unknown", "program", f"{low} opens something in a folder known only as it runs")
            elif target.lower().rstrip("/").endswith(OPEN_RISKY_POSIX):
                self.add("program", "program", f"{low} runs {target}", name=target[:160], paths=[place])
            else:
                self.touch("read", "open", f"opens {place} in its own program", [place],
                           name=posixpath.basename(place))


def _tar_overwrites(archive: str, dest: str) -> bool:
    """Unpacking would replace a file already in `dest`, or put one outside it."""
    try:
        with tarfile.open(archive, "r:*") as t:
            names = t.getnames()
    except (OSError, tarfile.TarError):
        return True
    return any(n.startswith("/") or ".." in n.split("/") or os.path.isfile(posixpath.join(dest, n)) for n in names)


def read(command: str, cwd: str, home: str | None = None) -> Reading:
    """Reads and sorts one bash command to be run in `cwd`; `home` is the person's home folder, which `~` and
    $HOME name. A command that does not parse comes back with errors."""
    if len(command) > COMMAND_MAX:
        return Reading(command, cwd, [], [f"the command is longer than {COMMAND_MAX} characters"])
    root = _tree(command)
    if root.has_error:
        stack, bad = [root], None
        while stack and bad is None:
            item = stack.pop()
            bad = item if item.is_error or item.is_missing else None
            stack.extend(reversed(item.children))
        near = command[bad.start_byte:bad.start_byte + 40] if bad is not None else command[:40]
        return Reading(command, cwd, [], [f"bash could not parse the command near {near!r}"])
    sorter = Sorter(cwd, home or os.path.expanduser("~"))
    sorter.survey(root)
    sorter.statement(root)
    acts = sorter.acts
    if any(a.kind == "network" and a.paths for a in acts) and any(a.kind in ("program", "install") for a in acts):
        acts.append(Act("hidden", "download_run", "downloads something and runs it in the same command"))
    return Reading(command, cwd, acts, [])


def gist(reading: Reading) -> str:
    """What a reading comes to, as one word: "never", "ask", "delete", "network", "write" or "read"."""
    kinds = {a.kind for a in reading.acts}
    if kinds & set(NEVER_KINDS):
        return "never"
    if reading.errors or kinds & {"unknown", "program", "install", "outside", "move_out"}:
        return "ask"
    if "delete" in kinds:
        return "delete"
    if "network" in kinds:
        return "network"
    if any(a.unresolved for a in reading.acts):
        return "ask"
    if kinds & {"change", "overwrite"}:
        return "write"
    return "read"
