"""What bashread.py knows about POSIX commands and places: the tables a bash command is sorted by, beside
read.py's (pstables.py). Anything not in them is "unknown" and asked."""
from __future__ import annotations

import re

from .pstables import EXE_INSTALL, INSTALLERS, INTERPRETERS, OPEN_RISKY, RUNNABLE

# The name a process substitution's pipe gets in an argument.
PIPE = "/dev/fd/63"
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
OPEN_RISKY_POSIX = (*OPEN_RISKY, ".app", ".command", ".tool", ".pkg", ".mpkg", ".dmg", ".desktop", ".appimage", ".deb",
                    ".rpm", ".run", ".terminal", ".workflow", ".scpt", ".applescript", ".scptd", ".prefpane", ".kext",
                    ".mobileconfig", ".webloc", ".inetloc", ".bash", ".zsh", ".csh", ".ksh", ".pl", ".rb", ".php")
SCRIPTS = (*RUNNABLE, ".bash", ".zsh", ".pl", ".rb", ".php", ".lua", ".r", ".command", ".tcl", ".awk", ".sed")
PACKAGES = (*INSTALLERS, ".pkg", ".mpkg", ".deb", ".rpm", ".appimage", ".run", ".dmg", ".snap", ".flatpakref")
# The folders whose programs are the system's own, so /bin/rm is rm.
BIN_DIRS = ("/bin", "/usr/bin", "/sbin", "/usr/sbin", "/usr/local/bin", "/usr/local/sbin", "/opt/homebrew/bin",
            "/opt/homebrew/sbin", "/run/current-system/sw/bin")
# Archivers and compressors.
ARCHIVERS = ("tar", "zip", "unzip", "gzip", "gunzip", "bzip2", "bunzip2", "xz", "unxz", "zstd", "unzstd", "lz4", "7z",
             "7za", "compress", "uncompress")
# Brace expansion ({a,b}, {1..3}) makes more than one word.
BRACES = re.compile(r"\{[^{}]*(,|\.\.)[^{}]*\}")
# What a variable may hold in arithmetic without running anything.
NUMERIC_VALUES = re.compile(r"-?\d+|\{-?\d+\.\.-?\d+(\.\.-?\d+)?\}")
