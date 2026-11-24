"""What read.py knows about PowerShell commands, Windows programs, .NET types and methods, and the registry:
the tables a command is sorted by. Anything not in them is "unknown" and asked."""
from __future__ import annotations

import re

PURE = {
    "select-object", "sort-object", "where-object", "foreach-object", "group-object", "measure-object", "format-table",
    "format-list", "format-wide", "format-custom", "out-string", "out-null", "out-default", "out-host", "write-output",
    "write-host", "write-verbose", "write-warning", "write-error", "write-information", "write-debug", "write-progress",
    "compare-object", "convertto-json", "convertfrom-json", "convertto-csv", "convertfrom-csv", "convertto-html",
    "convertto-xml", "convertfrom-stringdata", "get-member", "get-unique", "new-timespan", "get-random", "start-sleep",
    "get-date", "get-location", "split-path", "join-path", "get-variable", "set-variable", "new-variable",
    "clear-variable", "remove-variable", "get-culture", "get-uiculture", "get-host", "measure-command", "add-member",
    "new-guid", "get-command", "get-help", "test-json", "get-verb", "set-clipboard", "convertto-securestring", "get-error", "join-string", "get-psprovider", "get-alias",
}
# Reading files: the parameters that name what is read, and whether no path means the folder it runs in.
READS = {
    "get-childitem": ("list", True), "get-item": ("look", False), "get-itemproperty": ("look", False),
    "get-itempropertyvalue": ("look", False), "test-path": ("look", False), "resolve-path": ("look", False),
    "convert-path": ("look", False), "get-content": ("read", False), "get-filehash": ("read", False),
    "select-string": ("search", False), "import-csv": ("read", False), "get-acl": ("look", False),
    "select-xml": ("read", False), "import-clixml": ("read", False), "import-powershelldatafile": ("read", False),
    "format-hex": ("read", False),
}
# The reads that give a file's contents, not only its name.
CONTENT_READS = ("read", "search")
# Commands that set variables by name, and the common parameters that do: a constant may not stay one.
VARIABLE_CMDLETS = {"set-variable", "new-variable", "clear-variable", "remove-variable", "get-variable"}
# Readers and the file system's own value-less switches, which the binder leaves unbound after a quoted full path.
FS_READERS = {"get-childitem", "get-item", "get-content"}
FS_SWITCHES = {"file", "directory", "hidden", "readonly", "system", "raw", "followsymlink", "af", "ad", "ah", "as"}
VARIABLE_PARAMS = ("OutVariable", "PipelineVariable", "ErrorVariable", "WarningVariable", "InformationVariable")
# Members read off what comes down a pipeline (`ForEach-Object Name`) that only give a value back.
SAFE_MEMBERS = {
    "name", "fullname", "basename", "extension", "length", "lastwritetime", "creationtime", "lastaccesstime",
    "directoryname", "directory", "parent", "mode", "attributes", "exists", "count", "value", "values", "key", "keys",
    "path", "id", "processname", "workingset", "workingset64", "privatememorysize64", "cpu", "ws", "pm", "status",
    "displayname", "starttype", "size", "freespace", "used", "free", "root", "description", "line", "linenumber",
    "filename", "hash", "algorithm", "group", "psiscontainer", "isreadonly", "versioninfo", "productversion",
    "fileversion", "mainwindowtitle", "starttime", "handles", "sum", "average", "maximum", "minimum", "deviceid",
    "volumename", "drivetype", "label", "driveletter", "filesystem", "sizeremaining", "healthstatus", "matches",
    "lastwritetimeutc", "creationtimeutc", "company", "product", "linktype", "target", "pspath", "psparentpath",
    "pschildname", "ipaddress", "interfacealias", "caption", "version", "buildnumber",
}
# Methods that give a value back on a string but change files on a file (FileInfo.Replace): only on strings.
STRING_ONLY_METHODS = {"replace"}
STRING_MEMBERS = {
    "name", "basename", "fullname", "extension", "directoryname", "processname", "displayname", "description",
    "path", "line", "filename", "hash", "mainwindowtitle", "tostring", "trim", "trimstart", "trimend", "toupper",
    "tolower", "toupperinvariant", "tolowerinvariant", "substring", "replace", "normalize", "padleft", "padright",
    "remove", "insert", "format", "join", "getfilename", "getfilenamewithoutextension", "getextension",
    "getdirectoryname", "combine", "changeextension", "string", "system.string", "pschildname",
}
# Methods of Windows' management and shell objects that turn the computer off, change services or run things.
METHOD_KINDS = {"win32shutdown": "shutdown", "win32shutdowntracker": "shutdown", "reboot": "shutdown",
                "shutdown": "shutdown", "stopservice": "system", "startservice": "system", "changestartmode": "system",
                "pauseservice": "system", "resumeservice": "system", "setpowerstate": "system",
                "shellexecute": "hidden", "invokeverb": "hidden", "invokeverbex": "hidden"}
# [IO.File] and [IO.Directory] methods that only read what they are given.
FILE_READ_METHODS = {"readalltext", "readalllines", "readallbytes", "readlines", "exists", "getattributes",
                     "getlastwritetime", "getcreationtime", "getlastaccesstime", "getfiles", "getdirectories",
                     "enumeratefiles", "enumeratedirectories", "getfilesystementries", "enumeratefilesystementries"}
FILE_TYPES = ("io.file", "system.io.file", "io.directory", "system.io.directory")
READ_PARAMS = ("Path", "LiteralPath", "FilePath")
# Stages whose output is the files they list, and stages that only pass some of them on.
ITEM_SOURCES = {"get-childitem", "get-item", "resolve-path", "get-itemproperty"}
ITEM_FILTERS = {"where-object", "sort-object", "select-object", "out-null"}
# A listing's parameters that leave its items exactly as Python finds them; those that make a listing or a
# Select-Object hand on something else (names, streams, relative paths, picked properties).
LISTING_EXACT = {"path", "literalpath", "recurse", "force", "erroraction", "file", "directory"}
LISTING_RESHAPED = {"name", "stream", "relative"}
SELECT_RESHAPED = {"property", "expandproperty", "excludeproperty"}
# Modules that come with Windows, whose Get- and Test- commands only read.
INBOX_MODULES = {"storage", "nettcpip", "netadapter", "dnsclient", "netsecurity", "pnpdevice", "international",
                 "scheduledtasks", "defender", "bitlocker", "appx", "psreadline", "cimcmdlets", "printmanagement",
                 "smbshare", "netconnection", "packagemanagement", "powershellget", "dism", "netqos", "wifi",
                 "startlayout", "hyper-v", "netlbfo", "vpnclient", "windowsupdate", "configci", "trustedplatformmodule"}
# Facts about this computer, named by no path.
FACTS = {
    "get-psdrive": "disk", "get-volume": "disk", "get-disk": "disk", "get-physicaldisk": "disk",
    "get-partition": "disk", "get-computerinfo": "info", "get-process": "apps", "get-service": "info",
    "get-hotfix": "info", "get-timezone": "info", "get-netipaddress": "info", "get-netipconfiguration": "info",
    "get-netadapter": "info", "get-printer": "info", "get-pnpdevice": "info", "get-counter": "info",
    "get-startapps": "apps", "get-appxpackage": "apps", "get-package": "apps", "get-module": "info",
    "get-installedmodule": "apps", "get-winevent": "info", "get-eventlog": "info", "get-localuser": "info",
    "get-localgroup": "info", "get-executionpolicy": "info", "get-mppreference": "info",
    "get-mpcomputerstatus": "info", "get-netfirewallprofile": "info", "get-netfirewallrule": "info",
    "get-scheduledtask": "info", "get-uptime": "info", "get-ciminstance": "info", "get-wmiobject": "info",
    "get-cimclass": "info", "get-storagesubsystem": "disk", "get-psreadlineoption": "info",
}
DISK_CLASSES = ("win32_logicaldisk", "win32_volume", "win32_diskdrive", "msft_volume", "win32_diskpartition")
# File changes, each with its PowerShell parameters: (what, sources, destination).
CHANGES = {
    "new-item": ("new", ("Path",), ""), "mkdir": ("new", ("Path",), ""),
    "copy-item": ("copy", ("Path", "LiteralPath"), "Destination"),
    "move-item": ("move", ("Path", "LiteralPath"), "Destination"),
    "rename-item": ("rename", ("Path", "LiteralPath"), "NewName"),
    "remove-item": ("delete", ("Path", "LiteralPath"), ""),
    "clear-content": ("empty", ("Path", "LiteralPath"), ""),
    "set-content": ("write", ("Path", "LiteralPath"), ""), "add-content": ("append", ("Path", "LiteralPath"), ""),
    "out-file": ("write", ("FilePath", "LiteralPath"), ""), "export-csv": ("write", ("Path", "LiteralPath"), ""),
    "export-clixml": ("write", ("Path", "LiteralPath"), ""), "tee-object": ("write", ("FilePath", "LiteralPath"), ""),
    "set-itemproperty": ("attr", ("Path", "LiteralPath"), ""),
    "compress-archive": ("zip", ("Path", "LiteralPath"), "DestinationPath"),
    "expand-archive": ("unzip", ("Path", "LiteralPath"), "DestinationPath"),
}
NETWORK = {"invoke-webrequest": "Uri", "invoke-restmethod": "Uri", "start-bitstransfer": "Source",
           "send-mailmessage": "SmtpServer", "test-connection": "ComputerName", "test-netconnection": "ComputerName",
           "resolve-dnsname": "Name"}
INSTALL = {"install-module", "install-package", "install-script", "uninstall-module", "uninstall-package",
           "uninstall-script", "update-module", "update-script", "install-packageprovider", "add-appxpackage",
           "remove-appxpackage", "save-module", "save-package", "update-help"}
NEVER_CMDLETS = {
    "invoke-expression": "hidden", "add-type": "hidden", "set-alias": "hidden", "new-alias": "hidden",
    "import-alias": "hidden", "register-objectevent": "hidden", "register-engineevent": "hidden",
    "register-wmievent": "hidden", "start-job": "hidden", "start-threadjob": "hidden", "new-psdrive": "hidden",
    "new-module": "hidden", "register-scheduledjob": "system", "new-pssession": "system",
    "enter-pssession": "system", "invoke-wmimethod": "system", "invoke-cimmethod": "system",
    "set-wmiinstance": "system", "remove-wmiobject": "system", "set-ciminstance": "system",
    "new-ciminstance": "system", "remove-ciminstance": "system", "set-executionpolicy": "system",
    "unblock-file": "system", "set-acl": "system", "set-authenticodesignature": "system",
    "get-credential": "secrets", "convertfrom-securestring": "secrets", "export-pfxcertificate": "secrets",
    "export-certificate": "secrets", "get-pfxcertificate": "secrets", "get-storedcredential": "secrets",
    "restart-computer": "shutdown", "stop-computer": "shutdown", "new-itemproperty": "system",
    "remove-itemproperty": "system", "rename-itemproperty": "system", "copy-itemproperty": "system",
    "move-itemproperty": "system", "clear-itemproperty": "system", "clear-item": "system",
    "enable-psremoting": "system", "disable-psremoting": "system", "new-webserviceproxy": "system",
}
SYSTEM_NOUNS = ("service", "scheduledtask", "scheduledjob", "firewall", "mppreference", "mpthreat", "mpscan",
                "mpsignature", "executionpolicy", "computer", "localuser", "localgroup", "partition", "disk", "volume",
                "bitlocker", "windowsoptionalfeature", "windowscapability", "windowspackage", "netip", "netadapter",
                "dnsclient", "netroute", "netconnection", "tpm", "secureboot", "applocker", "processmitigation",
                "eventlog", "acl", "authenticode", "certificate", "psremoting", "pssession", "wsman", "date",
                "timezone", "culture", "winsystemlocale", "winuserlanguage", "winhomelocation", "computerrestore",
                "ciminstance", "wmi", "deliveryoptimization", "gpo", "gpregistry", "networkadapter", "vpn",
                "proxy", "smb", "printer", "windowsdefender", "uac")
READ_VERBS = ("get", "test", "measure", "select", "find", "search", "resolve", "compare", "convertto", "convertfrom",
              "format", "group", "sort", "split", "join", "confirm")
# Programs by file name.
EXE_READ = {"hostname", "whoami", "systeminfo", "tasklist", "where", "getmac", "driverquery", "chcp", "vol", "quser",
            "netstat", "nvidia-smi", "gpresult", "ver", "findstr", "tree", "fc", "comp", "more", "sort", "ipconfig",
            "wmic", "fsutil"}
# Those that can reach another computer with /s.
EXE_REMOTE = {"systeminfo", "tasklist", "getmac", "driverquery", "gpresult", "whoami", "quser"}
# nvidia-smi only asked, never told: anything else sets clocks, power or modes.
NVIDIA_READ = ("-q", "--query", "-l", "--list", "--format", "-i", "--id", "-d", "--display", "-h", "--help")
INTERPRETERS = ("python", "python3", "py", "pythonw", "node", "deno", "bun", "ruby", "perl", "php", "java", "javaw")
EXE_OPEN = {"notepad", "mspaint", "calc", "explorer", "write", "charmap"}
EXE_NET = {"ping", "tracert", "pathping", "nslookup", "curl", "wget", "ftp", "tftp", "nc", "ncat", "git"}
# git's subcommands that reach another computer; the rest work in the folder.
GIT_NET = {"clone", "fetch", "pull", "push", "ls-remote", "remote", "submodule", "send-email", "request-pull", "svn",
           "p4", "daemon", "http-backend", "instaweb", "credential"}
EXE_INSTALL = {"winget", "choco", "scoop", "msiexec", "pip", "pip3", "npm", "pnpm", "yarn", "gem", "cargo", "conda",
               "dotnet", "appinstaller"}
EXE_STOP = {"taskkill", "tskill"}
EXE_NEVER = {
    "cmd": "hidden", "powershell": "hidden", "pwsh": "hidden", "powershell_ise": "hidden", "wscript": "hidden",
    "cscript": "hidden", "mshta": "hidden", "rundll32": "hidden", "regsvr32": "hidden", "regsvcs": "hidden",
    "regasm": "hidden", "installutil": "hidden", "msbuild": "hidden", "bash": "hidden", "wsl": "hidden",
    "forfiles": "hidden", "pcalua": "hidden", "cmstp": "hidden", "mavinject": "hidden", "odbcconf": "hidden",
    "infdefaultinstall": "hidden", "msdt": "hidden", "certutil": "hidden", "bitsadmin": "hidden", "subst": "hidden",
    "conhost": "hidden", "scriptrunner": "hidden", "syncappvpublishingserver": "hidden", "msxsl": "hidden",
    "ieexec": "hidden", "presentationhost": "hidden", "hh": "hidden", "csc": "hidden", "vbc": "hidden", "jsc": "hidden",
    "atbroker": "hidden", "extrac32": "hidden", "finger": "hidden", "appvlp": "hidden", "xwizard": "hidden",
    "diskshadow": "system",
    "runas": "elevate", "gsudo": "elevate", "sudo": "elevate", "fodhelper": "elevate", "computerdefaults": "elevate",
    "sdclt": "elevate", "eventvwr": "elevate", "psexec": "elevate", "psexec64": "elevate",
    "shutdown": "shutdown", "logoff": "shutdown", "tsdiscon": "shutdown",
    "reg": "system", "regedit": "system", "regedt32": "system", "regini": "system", "bcdedit": "system",
    "bcdboot": "system", "bootrec": "system", "bootsect": "system", "diskpart": "system", "format": "system",
    "chkdsk": "system", "chkntfs": "system", "sfc": "system", "dism": "system", "schtasks": "system", "at": "system",
    "sc": "system", "net": "system", "net1": "system", "netsh": "system", "vssadmin": "system", "wbadmin": "system",
    "manage-bde": "system", "cipher": "system", "takeown": "system", "icacls": "system", "cacls": "system",
    "xcacls": "system", "setx": "system", "wevtutil": "system", "auditpol": "system", "secedit": "system",
    "gpupdate": "system", "gpedit": "system", "mmc": "system", "msconfig": "system", "winrm": "system",
    "winrs": "system", "ssh": "system", "scp": "system", "sftp": "system", "telnet": "system", "route": "system",
    "arp": "system", "mountvol": "system", "fdisk": "system", "defrag": "system", "esentutl": "system",
    "wusa": "system", "pnputil": "system", "devcon": "system", "powercfg": "system", "w32tm": "system",
    "control": "system", "services": "system", "taskschd": "system", "compmgmt": "system", "ntdsutil": "system",
    "nltest": "system", "ksetup": "system", "klist": "secrets", "cmdkey": "secrets", "vaultcmd": "secrets",
    "mimikatz": "secrets", "procdump": "secrets",
}
RUNNABLE = (".exe", ".com", ".bat", ".cmd", ".ps1", ".psm1", ".psd1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh",
            ".scr", ".pif", ".hta", ".cpl", ".lnk", ".jar", ".py", ".pyw", ".sh", ".url", ".library-ms",
            ".settingcontent-ms", ".diagcab", ".inf", ".dll", ".application", ".appref-ms")
INSTALLERS = (".msi", ".msp", ".msix", ".msixbundle", ".appx", ".appxbundle", ".appinstaller", ".msu")
# Opening these in their own program runs code, changes settings or installs something: asked like a program.
OPEN_RISKY = RUNNABLE + INSTALLERS + (
    ".reg", ".msc", ".chm", ".website", ".xbap", ".jnlp", ".wsc", ".sct", ".scf", ".theme", ".themepack",
    ".deskthemepack", ".search-ms", ".searchconnector-ms", ".cer", ".crt", ".der", ".p7b", ".xll", ".iqy", ".slk",
    ".docm", ".dotm", ".xlsm", ".xltm", ".xlam", ".pptm", ".potm", ".ppam", ".mht", ".mhtml", ".gadget", ".ps1xml",
    ".psc1", ".ws", ".vb", ".mof", ".job", ".lnk")
# Methods with no effect outside the command, and types whose static members are such.
PURE_METHODS = {
    "tostring", "trim", "trimend", "trimstart", "substring", "replace", "split", "toupper", "tolower",
    "toupperinvariant", "tolowerinvariant", "contains", "startswith", "endswith", "indexof", "lastindexof", "padleft",
    "padright", "equals", "compareto", "gettype", "add", "addrange", "adddays", "addhours", "addminutes",
    "addseconds", "addmonths", "addyears", "toshortdatestring", "tolongdatestring", "toshorttimestring", "insert",
    "remove", "removeat", "containskey", "containsvalue", "join", "format", "round", "floor", "ceiling", "abs", "max",
    "min", "pow", "sqrt", "log", "log10", "truncate", "parse", "tryparse", "toint32", "toint64", "todouble",
    "todecimal", "toboolean", "getfilename", "getfilenamewithoutextension", "getextension", "getdirectoryname",
    "combine", "changeextension", "isnullorempty", "isnullorwhitespace", "concat", "getdrives", "getfolderpath",
    "getenvironmentvariable", "normalize", "tochararray", "toarray", "reverse", "match", "matches", "ismatch",
    "escape", "unescape", "getenumerator", "sort", "clear", "getvalue", "where", "foreach", "sum", "average",
    "count", "distinct", "first", "last", "tolist", "now", "today", "fromfiletime", "tofiletime", "getbytes",
    "getstring", "frombase10", "newguid", "getrandomfilename", "gettemppath", "gettempfilename", "exists",
    "tolocaltime", "touniversaltime", "getpathroot", "ispathrooted", "hasextension", "totalgigabytes",
    "getinvalidfilenamechars", "getinvalidpathchars", "tryadd", "trygetvalue", "copy", "indexofany",
}
SAFE_TYPES = {"math", "system.math", "string", "system.string", "datetime", "system.datetime", "timespan",
              "system.timespan", "io.path", "system.io.path", "io.driveinfo", "system.io.driveinfo", "char",
              "system.char", "int", "int32", "int64", "long", "double", "decimal", "system.int32", "system.int64",
              "system.double", "system.decimal", "regex", "system.text.regularexpressions.regex", "guid",
              "system.guid", "array", "system.array", "environment", "system.environment", "bool", "system.boolean",
              "convert", "system.convert", "text.encoding", "system.text.encoding", "version", "system.version",
              "linq.enumerable", "system.linq.enumerable", "bitconverter", "system.bitconverter", "uri", "system.uri",
              "io.file", "system.io.file", "io.directory", "system.io.directory"}
NEVER_TYPES = ("scriptblock", "system.management.automation", "powershell", "runspacefactory", "reflection.",
               "system.reflection", "activator", "system.activator", "runtime.interopservices",
               "system.runtime.interopservices", "appdomain", "system.appdomain", "codedom", "microsoft.csharp",
               "wmiclass", "wmi", "wmisearcher", "system.management.", "adsi", "adsisearcher",
               "security.cryptography.protecteddata", "system.security.cryptography.protecteddata",
               "windows.security.credentials", "microsoft.win32.registry", "system.diagnostics.process",
               "diagnostics.process", "type", "system.type")
NET_TYPES = ("net.webclient", "system.net.webclient", "net.http", "system.net.http", "net.sockets", "system.net.sockets",
             "net.webrequest", "system.net.webrequest", "net.httpwebrequest", "system.net.httpwebrequest",
             "net.mail", "system.net.mail")
# Objects New-Object makes that only hold values.
PLAIN_OBJECTS = ("psobject", "pscustomobject", "system.collections.arraylist", "collections.arraylist",
                 "system.text.stringbuilder", "text.stringbuilder", "datetime", "system.datetime",
                 "system.collections.hashtable", "hashtable", "timespan", "system.timespan", "system.io.fileinfo",
                 "io.fileinfo", "system.io.directoryinfo", "io.directoryinfo", "system.io.driveinfo", "io.driveinfo")
GENERIC_COLLECTIONS = ("system.collections.generic.", "collections.generic.")
NEVER_METHODS = {"invoke", "invokereturnasis", "create", "frombase64string", "load", "loadfrom", "loadfile",
                 "getdelegateforfunctionpointer", "createinstance", "invokescript", "newscriptblock", "expandstring",
                 "addscript", "begininvoke", "invokemember", "setenvironmentvariable", "dynamicinvoke"}
NET_METHODS = {"downloadstring", "downloadfile", "downloaddata", "uploadstring", "uploadfile", "uploaddata",
               "openread", "openwrite", "getasync", "postasync", "putasync", "sendasync", "getstringasync",
               "getbytearrayasync", "getresponse", "send", "connect"}
# The registry keys a command may read: installed programs and the Windows version.
REGISTRY_READ = (r"hklm\software\microsoft\windows\currentversion\uninstall",
                 r"hklm\software\wow6432node\microsoft\windows\currentversion\uninstall",
                 r"hkcu\software\microsoft\windows\currentversion\uninstall",
                 r"hklm\software\microsoft\windows nt\currentversion",
                 # Where a program is: what Run and Start's search read to find it by its file name.
                 r"hklm\software\microsoft\windows\currentversion\app paths",
                 r"hklm\software\wow6432node\microsoft\windows\currentversion\app paths",
                 r"hkcu\software\microsoft\windows\currentversion\app paths")
# And the values it may change, after asking: light or dark, and file name extensions shown.
REGISTRY_WRITE = (r"hkcu\software\microsoft\windows\currentversion\themes\personalize",
                  r"hkcu\software\microsoft\windows\currentversion\explorer\advanced")
HIDDEN_VARS = {"executioncontext", "psdefaultparametervalues"}
# Names that would change how deletes and confirmations work, or hide what runs: never set, never passed.
DRY_DEFEATERS = re.compile(r"whatif|confirmpreference|psdefaultparametervalues", re.IGNORECASE)
VERBED = {"copy": "copies", "move": "moves", "rename": "renames", "zip": "zips", "unzip": "unzips"}
LOOPBACK = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "[::1]"}
