"""Windows' own limits on a command, which hold where the reading before it (read.py) was wrong.

The reading decides what a command may do; these limits are what Windows itself refuses it, whatever it really
does. Every command runs under a restricted copy of the person's own token (CreateRestrictedToken, as Chromium's
sandbox and Codex's Windows sandbox start their processes): no privilege but passing through folders, the
Administrators group good only for denying, and every access checked a second time against a list of SIDs that
holds the person's own and the app's SIDs (`sids`). Entries placed by guards.py deny those SIDs the app's home (so no
command reads, lists or changes the model keys' file, the settings or the browser pane's profile, by any path, while
its skills' folder stays readable), the secrets and network keys outside it, and the places that make code run later.
Its whole process tree is in a job object it cannot leave, whose UI limits
keep it off the clipboard, other programs' windows, the desktop, display and system settings, and shutting down.

Tiers, from the reading (acts.tier):
- "read": a command read as only reading also runs at low integrity. Windows refuses it every write to the person's
  files and their registry, and WMI and the Task Scheduler refuse to start anything for it outside the job. Its
  temporary folder is its own, in one of the app's labelled low, and is removed after it.
- "change": the integrity level of the person's own programs; its tree is ended with its job when the command ends.
- "program": as "change", but what it opens outlives the command, and the clipboard and other windows stay usable
  to it, since a program opened for the person is theirs to use; it carries neither GUARD_SID nor OFFLINE_SID.

What WMI starts for a command outside its job keeps the command's token and is ended (`strays`). Not held here, as
measured on Windows 11 without administrator rights: the network (a job's rate control only slows it; the optional
hardening, netguard.py, blocks it), reads and writes elsewhere in the person's profile that no guard covers, a
command of the change tier that asks Explorer over COM to start a program (Explorer starts it with the person's
full token), and one that registers a scheduled task (the hardening closes the Task Scheduler's folders). Those
stay with the reading, which reads such commands as running a program or changing the system, and the person's
question.
"""
from __future__ import annotations

import contextlib
import ctypes
import functools
import os
import shutil
import tempfile
import threading
import time

TIERS = ("read", "change", "program")
# Windows' types, spelled with ctypes' own so that importing this on another system works.
DWORD, WORD, UINT, BOOL, LPWSTR = ctypes.c_uint32, ctypes.c_uint16, ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p
# The app's own SID for commands: of the resource-manager authority, which no account or group is given, so no
# token of the person's carries it. A restricting SID cannot be a capability SID (S-1-15-3), which Windows rejects.
COMMANDS_SID = "S-1-9-1-2405443489-874036122-4286035555-1823921565"
# Of the same authority, carried by fewer tokens (`sids`): GUARD_SID by every command that is not a program's run,
# which the guards on secrets and on places that make code run later deny (guards.py); OFFLINE_SID by a command not
# read as using the network, which the guards on network tools' credentials deny and, with the optional hardening,
# a filter of Windows' own network stack blocks (netguard.py).
GUARD_SID = "S-1-9-1-929109962-2780505523-494882048-4200935409"
OFFLINE_SID = "S-1-9-1-2648098937-1802418873-3666617143-1379462614"
ADMINISTRATORS = "S-1-5-32-544"
LOCAL_ADMIN = "S-1-5-114"
LOW_INTEGRITY = "S-1-16-4096"
LOW_FOLDER = "mibo-low"
# The home's folder a command may read and run from (grants.Places.skills).
SKILLS = "skills"

# Token rights and classes.
TOKEN_ASSIGN_PRIMARY, TOKEN_DUPLICATE, TOKEN_QUERY, TOKEN_ADJUST_DEFAULT = 0x0001, 0x0002, 0x0008, 0x0080
TOKEN_USER_CLASS, TOKEN_GROUPS_CLASS, TOKEN_RESTRICTED_SIDS_CLASS, TOKEN_INTEGRITY_CLASS = 1, 2, 11, 25
DISABLE_MAX_PRIVILEGE = 0x1
SE_GROUP_ENABLED, SE_GROUP_USE_FOR_DENY_ONLY, SE_GROUP_INTEGRITY = 0x4, 0x10, 0x20
# Job object classes and limits.
JOB_ACCOUNTING, JOB_BASIC_UI_RESTRICTIONS, JOB_EXTENDED_LIMITS = 1, 4, 9
PROCESS_TERMINATE, PROCESS_QUERY_LIMITED_INFORMATION = 0x1, 0x1000
JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x400, 0x2000
UILIMIT_HANDLES, UILIMIT_READCLIPBOARD, UILIMIT_WRITECLIPBOARD = 0x1, 0x2, 0x4
UILIMIT_SYSTEMPARAMETERS, UILIMIT_DISPLAYSETTINGS, UILIMIT_GLOBALATOMS = 0x8, 0x10, 0x20
UILIMIT_DESKTOP, UILIMIT_EXITWINDOWS = 0x40, 0x80
UI_PROGRAM = UILIMIT_SYSTEMPARAMETERS | UILIMIT_DISPLAYSETTINGS | UILIMIT_DESKTOP | UILIMIT_EXITWINDOWS
UI_ALL = UI_PROGRAM | UILIMIT_HANDLES | UILIMIT_READCLIPBOARD | UILIMIT_WRITECLIPBOARD | UILIMIT_GLOBALATOMS
# Process creation.
CREATE_SUSPENDED, CREATE_UNICODE_ENVIRONMENT, EXTENDED_STARTUPINFO_PRESENT = 0x4, 0x400, 0x80000
CREATE_NO_WINDOW = 0x08000000
STARTF_USESTDHANDLES = 0x100
PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x20002
WAIT_OBJECT_0, INFINITE = 0, 0xFFFFFFFF
# Access control.
SE_FILE_OBJECT = 1
DACL_SECURITY_INFORMATION, LABEL_SECURITY_INFORMATION = 0x4, 0x10
GRANT_ACCESS, DENY_ACCESS = 1, 3
SUB_CONTAINERS_AND_OBJECTS_INHERIT = 0x3
TRUSTEE_IS_SID, TRUSTEE_IS_UNKNOWN = 0, 0
FILE_ALL_ACCESS, FILE_READ_EXECUTE = 0x1F01FF, 0x1200A9
SDDL_REVISION_1 = 1


class Unconfined(OSError):
    """Windows' limits for a command could not be set up, so it is not run."""


class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", DWORD)]


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [("cb", DWORD), ("lpReserved", LPWSTR), ("lpDesktop", LPWSTR),
                ("lpTitle", LPWSTR), ("dwX", DWORD), ("dwY", DWORD),
                ("dwXSize", DWORD), ("dwYSize", DWORD), ("dwXCountChars", DWORD),
                ("dwYCountChars", DWORD), ("dwFillAttribute", DWORD), ("dwFlags", DWORD),
                ("wShowWindow", WORD), ("cbReserved2", WORD), ("lpReserved2", ctypes.c_void_p),
                ("hStdInput", ctypes.c_void_p), ("hStdOutput", ctypes.c_void_p), ("hStdError", ctypes.c_void_p)]


class STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [("StartupInfo", STARTUPINFOW), ("lpAttributeList", ctypes.c_void_p)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", ctypes.c_void_p), ("hThread", ctypes.c_void_p), ("dwProcessId", DWORD),
                ("dwThreadId", DWORD)]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", DWORD), ("SchedulingClass", DWORD)]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION), ("IoInfo", ctypes.c_uint64 * 6),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


class TRUSTEE_W(ctypes.Structure):
    _fields_ = [("pMultipleTrustee", ctypes.c_void_p), ("MultipleTrusteeOperation", ctypes.c_int),
                ("TrusteeForm", ctypes.c_int), ("TrusteeType", ctypes.c_int), ("ptstrName", ctypes.c_void_p)]


class EXPLICIT_ACCESS_W(ctypes.Structure):
    _fields_ = [("grfAccessPermissions", DWORD), ("grfAccessMode", ctypes.c_int),
                ("grfInheritance", DWORD), ("Trustee", TRUSTEE_W)]


@functools.cache
def _api():
    """kernel32 and advapi32 with the signatures used here (instances of their own: ctypes.windll is shared)."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    p, d, b = ctypes.c_void_p, DWORD, BOOL
    sigs = {
        k32: {"GetCurrentProcess": ([], p), "CreateJobObjectW": ([p, LPWSTR], p),
              "SetInformationJobObject": ([p, ctypes.c_int, p, d], b), "AssignProcessToJobObject": ([p, p], b),
              "TerminateJobObject": ([p, UINT], b),
              "TerminateProcess": ([p, UINT], b), "CloseHandle": ([p], b), "ResumeThread": ([p], d),
              "WaitForSingleObject": ([p, d], d), "GetExitCodeProcess": ([p, ctypes.POINTER(d)], b),
              "InitializeProcThreadAttributeList": ([p, d, d, ctypes.POINTER(ctypes.c_size_t)], b),
              "UpdateProcThreadAttribute": ([p, d, ctypes.c_size_t, p, ctypes.c_size_t, p, p], b),
              "DeleteProcThreadAttributeList": ([p], None), "LocalFree": ([p], p),
              "CreateProcessAsUserW": ([p, LPWSTR, LPWSTR, p, p, b, d, p, LPWSTR, p, p],
                                       b),
              "OpenProcess": ([d, b, d], p), "IsProcessInJob": ([p, p, ctypes.POINTER(b)], b),
              "K32EnumProcesses": ([p, d, ctypes.POINTER(d)], b),
              "QueryInformationJobObject": ([p, ctypes.c_int, p, d, p], b)},
        adv: {"OpenProcessToken": ([p, d, ctypes.POINTER(p)], b),
              "GetTokenInformation": ([p, ctypes.c_int, p, d, ctypes.POINTER(d)], b),
              "SetTokenInformation": ([p, ctypes.c_int, p, d], b),
              "CreateRestrictedToken": ([p, d, d, p, d, p, d, p, ctypes.POINTER(p)], b),
              "ConvertStringSidToSidW": ([LPWSTR, ctypes.POINTER(p)], b),
              "ConvertSidToStringSidW": ([p, ctypes.POINTER(LPWSTR)], b),
              "EqualSid": ([p, p], b), "GetLengthSid": ([p], d),
              "GetNamedSecurityInfoW": ([LPWSTR, ctypes.c_int, d, p, p, ctypes.POINTER(p), p,
                                         ctypes.POINTER(p)], d),
              "SetNamedSecurityInfoW": ([LPWSTR, ctypes.c_int, d, p, p, p, p], d),
              "SetEntriesInAclW": ([DWORD, p, p, ctypes.POINTER(p)], d),
              "GetAclInformation": ([p, p, d, ctypes.c_int], b), "GetAce": ([p, d, ctypes.POINTER(p)], b),
              "ConvertStringSecurityDescriptorToSecurityDescriptorW": ([LPWSTR, d, ctypes.POINTER(p), p], b),
              "GetSecurityDescriptorSacl": ([p, ctypes.POINTER(b), ctypes.POINTER(p), ctypes.POINTER(b)], b)},
    }
    for dll, funcs in sigs.items():
        for name, (args, res) in funcs.items():
            fn = getattr(dll, name)
            fn.argtypes, fn.restype = args, res
    return k32, adv


def _ok(result, what: str):
    """`result` when the call succeeded; else Unconfined with Windows' own error."""
    if not result:
        error = ctypes.get_last_error()
        raise Unconfined(error, f"{what}: {ctypes.FormatError(error).strip()}")
    return result


def _done(status: int, what: str) -> None:
    """For the calls that answer with an error code (0 is success)."""
    if status:
        raise Unconfined(status, f"{what}: {ctypes.FormatError(status).strip()}")


class _Sid:
    """A SID made from its text, freed with the object."""

    def __init__(self, text: str):
        k32, adv = _api()
        self.value = ctypes.c_void_p()
        _ok(adv.ConvertStringSidToSidW(text, ctypes.byref(self.value)), "ConvertStringSidToSid")
        self._free = k32.LocalFree

    def __del__(self):
        if self.value:
            self._free(self.value)


def _sid_text(sid) -> str:
    k32, adv = _api()
    out = LPWSTR()
    _ok(adv.ConvertSidToStringSidW(sid, ctypes.byref(out)), "ConvertSidToStringSid")
    try:
        return out.value
    finally:
        k32.LocalFree(ctypes.cast(out, ctypes.c_void_p))


def _token_info(token, cls: int) -> ctypes.Array:
    _, adv = _api()
    size = DWORD()
    adv.GetTokenInformation(token, cls, None, 0, ctypes.byref(size))
    buf = ctypes.create_string_buffer(size.value)
    _ok(adv.GetTokenInformation(token, cls, buf, size, ctypes.byref(size)), "GetTokenInformation")
    return buf


def sids(tier: str, online: bool) -> list[str]:
    """The app's SIDs a command's token carries: COMMANDS_SID always (the app's own places); GUARD_SID unless it runs
    a program (secrets and the places that make code run later; a program opened or installed for the person may need
    its browser profile, its credentials or a startup entry); OFFLINE_SID when it is neither a program's run nor read
    as using the network (network tools' credentials, and the network itself with the hardening on)."""
    if tier == "program":
        return [COMMANDS_SID]
    return [COMMANDS_SID, GUARD_SID] + ([] if online else [OFFLINE_SID])


def _token(tier: str, online: bool = False):
    """The restricted token a command of `tier` runs under (its handle, to close)."""
    k32, adv = _api()
    own = ctypes.c_void_p()
    _ok(adv.OpenProcessToken(k32.GetCurrentProcess(), TOKEN_ASSIGN_PRIMARY | TOKEN_DUPLICATE | TOKEN_QUERY
                             | TOKEN_ADJUST_DEFAULT, ctypes.byref(own)), "OpenProcessToken")
    try:
        user_buf = _token_info(own, TOKEN_USER_CLASS)
        groups_buf = _token_info(own, TOKEN_GROUPS_CLASS)
        count = DWORD.from_buffer(groups_buf).value
        groups = (SID_AND_ATTRIBUTES * count).from_buffer(groups_buf, ctypes.sizeof(ctypes.c_void_p))
        # The second check passes where the person's own token would: their SID and every group they use, the
        # sign-in session's among them; the app's own SIDs are what the guards' entries deny.
        restricting = [SID_AND_ATTRIBUTES.from_buffer(user_buf).Sid]
        restricting += [g.Sid for g in groups if g.Attributes & SE_GROUP_ENABLED
                        and not g.Attributes & (SE_GROUP_USE_FOR_DENY_ONLY | SE_GROUP_INTEGRITY)]
        ours = [_Sid(s) for s in sids(tier, online)]
        made = [_Sid(ADMINISTRATORS), _Sid(LOCAL_ADMIN)]
        restricting += [s.value for s in ours]
        deny = (SID_AND_ATTRIBUTES * 2)(*(SID_AND_ATTRIBUTES(s.value, 0) for s in made))
        restrict = (SID_AND_ATTRIBUTES * len(restricting))(*(SID_AND_ATTRIBUTES(s, 0) for s in restricting))
        token = ctypes.c_void_p()
        _ok(adv.CreateRestrictedToken(own, DISABLE_MAX_PRIVILEGE, len(deny), deny, 0, None, len(restrict), restrict,
                                      ctypes.byref(token)), "CreateRestrictedToken")
    finally:
        k32.CloseHandle(own)
    if tier != "read":
        # The app's own level, which is medium: commands are not run while it runs as administrator (panel.ready).
        return token
    try:
        level = _Sid(LOW_INTEGRITY)
        label = SID_AND_ATTRIBUTES(level.value, SE_GROUP_INTEGRITY)
        _ok(adv.SetTokenInformation(token, TOKEN_INTEGRITY_CLASS, ctypes.byref(label),
                                    ctypes.sizeof(label) + adv.GetLengthSid(level.value)), "SetTokenInformation")
    except Unconfined:
        k32.CloseHandle(token)
        raise
    return token


# The jobs of this app's commands still running, and of the programs they opened (`strays`).
_JOBS: set = set()
_JOBS_LOCK = threading.RLock()


class Job:
    """The job object a command's whole tree runs in: no way out of it, and the tier's limits."""

    def __init__(self, tier: str):
        k32, _ = _api()
        self.k32 = k32
        self.tier = tier
        self.handle = _ok(k32.CreateJobObjectW(None, None), "CreateJobObject")
        try:
            self.limit(tier)
        except Unconfined:
            self.close()
            raise
        with _JOBS_LOCK:
            _JOBS.add(self)

    def limit(self, tier: str) -> None:
        """The tier's limits; a "change" job made ahead is loosened so for a "program". Breakaway is never allowed."""
        limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION | (
            0 if tier == "program" else JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)
        _ok(self.k32.SetInformationJobObject(self.handle, JOB_EXTENDED_LIMITS, ctypes.byref(limits),
                                             ctypes.sizeof(limits)), "SetInformationJobObject")
        ui = DWORD(UI_PROGRAM if tier == "program" else UI_ALL)
        _ok(self.k32.SetInformationJobObject(self.handle, JOB_BASIC_UI_RESTRICTIONS, ctypes.byref(ui),
                                             ctypes.sizeof(ui)), "SetInformationJobObject")

    def end(self) -> None:
        self.k32.TerminateJobObject(self.handle, 1)

    def close(self) -> None:
        """Closing the last handle ends what is left in the tree. A "program" job is kept while what it opened runs,
        so that `strays` knows those processes for the app's own."""
        if self.handle and (self.tier != "program" or not self.running()):
            self.k32.CloseHandle(self.handle)
            self.handle = None
            with _JOBS_LOCK:
                _JOBS.discard(self)

    def running(self) -> int:
        """How many processes are in it now."""
        info = (DWORD * 12)()  # JOBOBJECT_BASIC_ACCOUNTING_INFORMATION: four times, then counts
        self.k32.QueryInformationJobObject(self.handle, JOB_ACCOUNTING, info, ctypes.sizeof(info), None)
        return info[10]


def strays() -> int:
    """Ends every process whose token carries COMMANDS_SID but that is in no job at all: what WMI started for a
    command (Win32_Process.Create starts it from WMI's own host, with the command's token, outside every job, as
    measured). Every command of this app, or of another copy of it, is in a job from its start, so none is ended.
    How many were ended."""
    k32, adv = _api()
    with _JOBS_LOCK:
        for job in [j for j in _JOBS if j.tier == "program" and j.handle and not j.running()]:
            job.close()
    pids = (DWORD * 4096)()
    size = DWORD()
    if not k32.K32EnumProcesses(pids, ctypes.sizeof(pids), ctypes.byref(size)):
        return 0
    ours, ended = _Sid(COMMANDS_SID), 0
    for pid in pids[:size.value // ctypes.sizeof(DWORD)]:
        process = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_TERMINATE, False, pid)
        if not process:
            continue
        try:
            token = ctypes.c_void_p()
            if not adv.OpenProcessToken(process, TOKEN_QUERY, ctypes.byref(token)):
                continue
            try:
                restricted = _token_info(token, TOKEN_RESTRICTED_SIDS_CLASS)
            except Unconfined:
                continue
            finally:
                k32.CloseHandle(token)
            count = DWORD.from_buffer(restricted).value
            sids = (SID_AND_ATTRIBUTES * count).from_buffer(restricted, ctypes.sizeof(ctypes.c_void_p))
            if not any(adv.EqualSid(g.Sid, ours.value) for g in sids):
                continue
            inside = BOOL()
            if not k32.IsProcessInJob(process, None, ctypes.byref(inside)) or inside.value:
                continue
            ended += bool(k32.TerminateProcess(process, 1))
        finally:
            k32.CloseHandle(process)
    return ended


class Process:
    """A started command's PowerShell, as run.py uses a subprocess.Popen: its pipes, poll, wait and exit code."""

    def __init__(self, handle, pid: int, stdin, stdout, stderr, temp: str = ""):
        self.k32 = _api()[0]
        self.handle, self.pid = handle, pid
        self.stdin, self.stdout, self.stderr = stdin, stdout, stderr
        self.returncode: int | None = None
        # A "read" command's own temporary folder, removed once it has ended (`clean`).
        self.temp = temp

    def clean(self) -> None:
        if self.temp:
            shutil.rmtree(self.temp, ignore_errors=True)
            self.temp = ""

    def poll(self) -> int | None:
        if self.returncode is None and self.k32.WaitForSingleObject(self.handle, 0) == WAIT_OBJECT_0:
            code = DWORD()
            self.k32.GetExitCodeProcess(self.handle, ctypes.byref(code))
            self.returncode = code.value
            self.k32.CloseHandle(self.handle)
        return self.returncode

    def wait(self) -> int:
        if self.returncode is None:
            self.k32.WaitForSingleObject(self.handle, INFINITE)
        return self.poll()


def _environment_block(env: dict) -> ctypes.Array:
    text = "".join(f"{k}={v}\0" for k, v in sorted(env.items(), key=lambda kv: kv[0].upper())) + "\0"
    return ctypes.create_unicode_buffer(text, len(text))


def start(command_line: str, cwd: str, env: dict, tier: str, online: bool = False) -> tuple[Process, Job]:
    """Starts `command_line` under the token of `tier` (and `online`: read as using the network, see `sids`), in a
    job of its own before it runs a single instruction, with pipes for its standard streams and no other handle of
    this app's. Unconfined when any of it fails."""
    if tier not in TIERS:
        raise Unconfined(0, f"no such tier: {tier}")
    k32, _ = _api()
    temp = ""
    if tier == "read":
        # A folder of its own in the app's low one, which it inherits the label from; removed after it (`clean`).
        try:
            temp = tempfile.mkdtemp(prefix="run-", dir=low_folder())
        except OSError as e:
            raise Unconfined(e.errno or 0, f"temporary folder: {e}") from e
        env = {**env, "TEMP": temp, "TMP": temp}
    try:
        job = Job(tier)
    except Unconfined:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    fds = [*os.pipe(), *os.pipe(), *os.pipe()]
    theirs = [fds[0], fds[3], fds[5]]
    ours = [fds[1], fds[2], fds[4]]
    token = attributes = None
    info = PROCESS_INFORMATION()
    try:
        handles = (ctypes.c_void_p * 3)(*(_handle(fd) for fd in theirs))
        startup = STARTUPINFOEXW()
        startup.StartupInfo.cb = ctypes.sizeof(startup)
        startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES
        startup.StartupInfo.hStdInput, startup.StartupInfo.hStdOutput, startup.StartupInfo.hStdError = handles
        size = ctypes.c_size_t()
        k32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
        attributes = ctypes.create_string_buffer(size.value)
        _ok(k32.InitializeProcThreadAttributeList(attributes, 1, 0, ctypes.byref(size)),
            "InitializeProcThreadAttributeList")
        # Only the three pipe ends are inherited, whatever else this app holds open.
        _ok(k32.UpdateProcThreadAttribute(attributes, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST, handles,
                                          ctypes.sizeof(handles), None, None), "UpdateProcThreadAttribute")
        startup.lpAttributeList = ctypes.cast(attributes, ctypes.c_void_p)
        token = _token(tier, online)
        line = ctypes.create_unicode_buffer(command_line)
        _ok(k32.CreateProcessAsUserW(token, None, line, None, None, True,
                                     CREATE_SUSPENDED | CREATE_NO_WINDOW | CREATE_UNICODE_ENVIRONMENT
                                     | EXTENDED_STARTUPINFO_PRESENT, _environment_block(env), cwd,
                                     ctypes.byref(startup), ctypes.byref(info)), "CreateProcessAsUser")
        try:
            _ok(k32.AssignProcessToJobObject(job.handle, info.hProcess), "AssignProcessToJobObject")
        except Unconfined:
            k32.TerminateJobObject(job.handle, 1)
            # Not yet in the job, so ended on its own: it has not run an instruction.
            k32.TerminateProcess(info.hProcess, 1)
            k32.CloseHandle(info.hProcess)
            raise
        k32.ResumeThread(info.hThread)
    except BaseException:
        job.close()
        for fd in ours:
            os.close(fd)
        if temp:
            shutil.rmtree(temp, ignore_errors=True)
        raise
    finally:
        if info.hThread:
            k32.CloseHandle(info.hThread)
        if token:
            k32.CloseHandle(token)
        if attributes is not None:
            k32.DeleteProcThreadAttributeList(attributes)
        for fd in theirs:
            os.close(fd)
    process = Process(info.hProcess, info.dwProcessId, os.fdopen(ours[0], "wb"), os.fdopen(ours[1], "rb"),
                      os.fdopen(ours[2], "rb"), temp)
    return process, job


def _handle(fd: int) -> int:
    import msvcrt
    handle = msvcrt.get_osfhandle(fd)
    os.set_handle_inheritable(handle, True)
    return handle


# ---------------------------------------------------------------- entries on folders


def _entry(path: str, sid: str, mode: int, rights: int) -> None:
    """Adds an entry for `sid` to `path`'s access list, inherited by everything in it; Windows carries it down to
    what is there now."""
    k32, adv = _api()
    dacl, descriptor, merged = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
    _done(adv.GetNamedSecurityInfoW(path, SE_FILE_OBJECT, DACL_SECURITY_INFORMATION, None, None, ctypes.byref(dacl),
                                    None, ctypes.byref(descriptor)), "GetNamedSecurityInfo")
    trustee = _Sid(sid)
    try:
        access = EXPLICIT_ACCESS_W(rights, mode, SUB_CONTAINERS_AND_OBJECTS_INHERIT,
                                   TRUSTEE_W(None, 0, TRUSTEE_IS_SID, TRUSTEE_IS_UNKNOWN, trustee.value))
        _done(adv.SetEntriesInAclW(1, ctypes.byref(access), dacl, ctypes.byref(merged)), "SetEntriesInAcl")
        _done(adv.SetNamedSecurityInfoW(path, SE_FILE_OBJECT, DACL_SECURITY_INFORMATION, None, None, merged, None),
              "SetNamedSecurityInfo")
    finally:
        k32.LocalFree(merged)
        k32.LocalFree(descriptor)


@functools.cache
def low_folder() -> str:
    """The temporary folder of a command that only reads: the app's own, labelled low so that such a command may
    write there and nowhere else."""
    k32, adv = _api()
    path = os.path.join(tempfile.gettempdir(), LOW_FOLDER)
    os.makedirs(path, exist_ok=True)
    # Changing a label takes the right to change the owner, which only full control gives the person.
    own = ctypes.c_void_p()
    _ok(adv.OpenProcessToken(k32.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(own)), "OpenProcessToken")
    try:
        me = _sid_text(SID_AND_ATTRIBUTES.from_buffer(_token_info(own, TOKEN_USER_CLASS)).Sid)
    finally:
        k32.CloseHandle(own)
    _entry(path, me, GRANT_ACCESS, FILE_ALL_ACCESS)
    descriptor, sacl = ctypes.c_void_p(), ctypes.c_void_p()
    present, defaulted = BOOL(), BOOL()
    # A mandatory label: low, no write up, inherited by files and folders.
    _ok(adv.ConvertStringSecurityDescriptorToSecurityDescriptorW("S:(ML;OICI;NW;;;LW)", SDDL_REVISION_1,
                                                                ctypes.byref(descriptor), None),
        "ConvertStringSecurityDescriptorToSecurityDescriptor")
    try:
        _ok(adv.GetSecurityDescriptorSacl(descriptor, ctypes.byref(present), ctypes.byref(sacl),
                                          ctypes.byref(defaulted)), "GetSecurityDescriptorSacl")
        _done(adv.SetNamedSecurityInfoW(path, SE_FILE_OBJECT, LABEL_SECURITY_INFORMATION, None, None, None, sacl),
              "SetNamedSecurityInfo")
    finally:
        k32.LocalFree(descriptor)
    # Folders of commands that never ended cleanly (the app was stopped), a day on.
    for entry in os.scandir(path):
        with contextlib.suppress(OSError):
            if entry.name.startswith("run-") and time.time() - entry.stat().st_mtime > 86400:
                shutil.rmtree(entry.path, ignore_errors=True)
    return path
