"""The optional hardening, set up once with administrator rights: commands not read as using the network cannot
reach it, and no command can register a scheduled task.

Network. Windows' own network stack (the Windows Filtering Platform) is given a sublayer of the app's, holding two
filters on each of the four layers where a connection is allowed (outgoing and accepted, IPv4 and IPv6). Both
match on the token of the process making the connection, by a security descriptor (FWPM_CONDITION_ALE_USER_ID):
- a block filter whose descriptor allows the person's own SID, which every token of theirs carries (a restricted
  one only if its list of restricting SIDs has it, as every command's token does);
- above it, a permit filter whose descriptor allows the person's own SID and denies OFFLINE_SID (confine.sids), so
  it matches every token of theirs except a command's that carries OFFLINE_SID.
A command not read as using the network so falls through to the block; any other process of the person's is
permitted by this sublayer (a soft permit: the Windows Firewall's own rules still apply to it), and a process of
another account, a service or an AppContainer (whose access needs an entry for its package) matches neither.
Loopback is blocked too, so such a command cannot reach the app's own local server or other local ones. A name
looked up through Windows' resolver is looked up by the DNS Client service, not by the command, and is not held.

Scheduled tasks. Each folder of the Task Scheduler is given a deny entry for GUARD_SID, so a command that is not a
program's run cannot register or change a task, which would run later outside every limit here.

`python -m mibo.shell.netguard on|off <record> <SID>` (or `mibo netguard`) does it, started from Settings through
the system's elevation prompt; it is the only part of the app that runs elevated. It is idempotent, and `off`
removes exactly what `on` added (the filters and sublayer by their fixed keys, each folder's descriptor as it was
before, from the record).
"""
from __future__ import annotations

import contextlib
import ctypes
import json
import os
import sys
import time
import uuid

from .confine import GUARD_SID, OFFLINE_SID

# Fixed keys, so that `on` again finds what is there and `off` takes exactly it away.
SUBLAYER = uuid.UUID("6f0b1a52-8d3e-4b7e-9a51-2f6c1e0d7a10")
LAYERS = {  # FWPM_LAYER_ALE_AUTH_CONNECT_V4/V6, FWPM_LAYER_ALE_AUTH_RECV_ACCEPT_V4/V6
    "connect4": uuid.UUID("c38d57d1-05a7-4c33-904f-7fbceee60e82"),
    "connect6": uuid.UUID("4a72393b-319f-44bc-84c3-ba54dcb3b6b4"),
    "accept4": uuid.UUID("e1cd9fe7-f4b5-4273-96c0-592e487b8650"),
    "accept6": uuid.UUID("a3b42c97-9f04-4672-b87e-cee9c483257f"),
}
CONDITION_ALE_USER_ID = uuid.UUID("af043a0a-b34d-4f86-979c-c90371af6e66")
# One key for each (layer, action), made from the sublayer's.
FILTERS = {(name, action): uuid.uuid5(SUBLAYER, f"{name}-{action}") for name in LAYERS for action in ("permit", "block")}

RPC_C_AUTHN_WINNT = 10
FWP_ACTION_BLOCK, FWP_ACTION_PERMIT = 0x1001, 0x1002
FWP_MATCH_EQUAL = 0
FWP_UINT8, FWP_SECURITY_DESCRIPTOR_TYPE = 1, 14
FWPM_FILTER_FLAG_PERSISTENT, FWPM_SUBLAYER_FLAG_PERSISTENT = 0x1, 0x1
FWP_E_ALREADY_EXISTS, FWP_E_FILTER_NOT_FOUND, FWP_E_SUBLAYER_NOT_FOUND = 0x80320009, 0x80320003, 0x80320007
TASK_FOLDER_DENY = f"(D;OICI;FA;;;{GUARD_SID})"


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16), ("Data3", ctypes.c_uint16),
                ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def of(cls, value: uuid.UUID) -> GUID:
        return cls.from_buffer_copy(value.bytes_le)

    def uuid(self) -> uuid.UUID:
        return uuid.UUID(bytes_le=bytes(self))


class DISPLAY_DATA(ctypes.Structure):
    _fields_ = [("name", ctypes.c_wchar_p), ("description", ctypes.c_wchar_p)]


class BYTE_BLOB(ctypes.Structure):
    _fields_ = [("size", ctypes.c_uint32), ("data", ctypes.c_void_p)]


class VALUE(ctypes.Structure):
    """FWP_VALUE0 and FWP_CONDITION_VALUE0: a type and one pointer-sized union."""
    _fields_ = [("type", ctypes.c_int), ("value", ctypes.c_uint64)]


class CONDITION(ctypes.Structure):
    _fields_ = [("fieldKey", GUID), ("matchType", ctypes.c_int), ("conditionValue", VALUE)]


class ACTION(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint32), ("filterType", GUID)]


class CONTEXT(ctypes.Union):
    _fields_ = [("rawContext", ctypes.c_uint64), ("providerContextKey", GUID)]


class FILTER(ctypes.Structure):
    _fields_ = [("filterKey", GUID), ("displayData", DISPLAY_DATA), ("flags", ctypes.c_uint32),
                ("providerKey", ctypes.c_void_p), ("providerData", BYTE_BLOB), ("layerKey", GUID),
                ("subLayerKey", GUID), ("weight", VALUE), ("numFilterConditions", ctypes.c_uint32),
                ("filterCondition", ctypes.c_void_p), ("action", ACTION), ("context", CONTEXT),
                ("reserved", ctypes.c_void_p), ("filterId", ctypes.c_uint64), ("effectiveWeight", VALUE)]


class SUBLAYER_(ctypes.Structure):
    _fields_ = [("subLayerKey", GUID), ("displayData", DISPLAY_DATA), ("flags", ctypes.c_uint32),
                ("providerKey", ctypes.c_void_p), ("providerData", BYTE_BLOB), ("weight", ctypes.c_uint16)]


def _fwp():
    dll = ctypes.WinDLL("fwpuclnt")
    p = ctypes.c_void_p
    for name, args in (("FwpmEngineOpen0", [p, ctypes.c_uint32, p, p, ctypes.POINTER(p)]),
                       ("FwpmEngineClose0", [p]), ("FwpmTransactionBegin0", [p, ctypes.c_uint32]),
                       ("FwpmTransactionCommit0", [p]), ("FwpmTransactionAbort0", [p]),
                       ("FwpmSubLayerAdd0", [p, p, p]), ("FwpmSubLayerDeleteByKey0", [p, p]),
                       ("FwpmFilterAdd0", [p, p, p, ctypes.POINTER(ctypes.c_uint64)]),
                       ("FwpmFilterDeleteByKey0", [p, p]), ("FwpmFilterGetByKey0", [p, p, ctypes.POINTER(p)]),
                       ("FwpmFilterCreateEnumHandle0", [p, p, ctypes.POINTER(p)]),
                       ("FwpmFilterEnum0", [p, p, ctypes.c_uint32, ctypes.POINTER(p), ctypes.POINTER(ctypes.c_uint32)]),
                       ("FwpmFilterDestroyEnumHandle0", [p, p]), ("FwpmFreeMemory0", [p])):
        fn = getattr(dll, name)
        fn.argtypes, fn.restype = args, ctypes.c_uint32
    return dll


def _check(status: int, what: str, allowed: tuple = ()) -> None:
    if status and status not in allowed:
        raise OSError(status, f"{what}: 0x{status:08x}")


def _descriptor(sddl: str) -> ctypes.Array:
    """A self-relative security descriptor's bytes."""
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    sd, size = ctypes.c_void_p(), ctypes.c_uint32()
    adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32,
                                                                       ctypes.POINTER(ctypes.c_void_p),
                                                                       ctypes.POINTER(ctypes.c_uint32)]
    if not adv.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(sd), ctypes.byref(size)):
        raise OSError(ctypes.get_last_error(), "ConvertStringSecurityDescriptor")
    data = (ctypes.c_ubyte * size.value).from_buffer_copy(ctypes.string_at(sd, size.value))
    ctypes.WinDLL("kernel32").LocalFree(sd)
    return data


def descriptors(user_sid: str) -> dict:
    """The two filters' descriptors, as SDDL."""
    return {"permit": f"D:(D;;CC;;;{OFFLINE_SID})(A;;CC;;;{user_sid})", "block": f"D:(A;;CC;;;{user_sid})"}


class Engine:
    def __init__(self):
        self.dll = _fwp()
        self.handle = ctypes.c_void_p()
        _check(self.dll.FwpmEngineOpen0(None, RPC_C_AUTHN_WINNT, None, None, ctypes.byref(self.handle)),
               "FwpmEngineOpen0")

    def close(self) -> None:
        self.dll.FwpmEngineClose0(self.handle)

    def filters(self, layer: uuid.UUID) -> list[dict]:
        """The filters on a layer: key, sublayer, action, display name (to read what is there)."""
        enum, rows = ctypes.c_void_p(), []
        _check(self.dll.FwpmFilterCreateEnumHandle0(self.handle, None, ctypes.byref(enum)), "FwpmFilterCreateEnumHandle0")
        try:
            while True:
                entries, count = ctypes.c_void_p(), ctypes.c_uint32()
                _check(self.dll.FwpmFilterEnum0(self.handle, enum, 256, ctypes.byref(entries), ctypes.byref(count)),
                       "FwpmFilterEnum0")
                if not count.value:
                    break
                pointers = (ctypes.c_void_p * count.value).from_address(entries.value)
                for pointer in pointers:
                    f = FILTER.from_address(pointer)
                    if f.layerKey.uuid() == layer:
                        rows.append({"key": f.filterKey.uuid(), "sublayer": f.subLayerKey.uuid(),
                                     "action": f.action.type, "name": f.displayData.name or "",
                                     "conditions": f.numFilterConditions})
                self.dll.FwpmFreeMemory0(ctypes.byref(entries))
        finally:
            self.dll.FwpmFilterDestroyEnumHandle0(self.handle, enum)
        return rows

    def on(self, user_sid: str) -> list[str]:
        """Adds the sublayer and the filters that are not there yet; what it added."""
        added, keep = [], []
        _check(self.dll.FwpmTransactionBegin0(self.handle, 0), "FwpmTransactionBegin0")
        try:
            sub = SUBLAYER_(GUID.of(SUBLAYER), DISPLAY_DATA("Mibo commands", "Commands not read as using the network"),
                            FWPM_SUBLAYER_FLAG_PERSISTENT, None, BYTE_BLOB(0, None), 0x100)
            status = self.dll.FwpmSubLayerAdd0(self.handle, ctypes.byref(sub), None)
            _check(status, "FwpmSubLayerAdd0", (FWP_E_ALREADY_EXISTS,))
            if not status:
                added.append(f"sublayer {SUBLAYER}")
            for (name, action), key in FILTERS.items():
                sd = _descriptor(descriptors(user_sid)[action])
                blob = BYTE_BLOB(len(sd), ctypes.addressof(sd))
                condition = CONDITION(GUID.of(CONDITION_ALE_USER_ID), FWP_MATCH_EQUAL,
                                      VALUE(FWP_SECURITY_DESCRIPTOR_TYPE, ctypes.addressof(blob)))
                f = FILTER()
                f.filterKey, f.subLayerKey, f.layerKey = GUID.of(key), GUID.of(SUBLAYER), GUID.of(LAYERS[name])
                f.displayData = DISPLAY_DATA(f"Mibo commands: {action} ({name})", None)
                f.flags = FWPM_FILTER_FLAG_PERSISTENT
                f.weight = VALUE(FWP_UINT8, 15 if action == "permit" else 1)
                f.numFilterConditions, f.filterCondition = 1, ctypes.addressof(condition)
                f.action.type = FWP_ACTION_PERMIT if action == "permit" else FWP_ACTION_BLOCK
                keep += [sd, blob, condition]
                filter_id = ctypes.c_uint64()
                status = self.dll.FwpmFilterAdd0(self.handle, ctypes.byref(f), None, ctypes.byref(filter_id))
                _check(status, f"FwpmFilterAdd0 {name} {action}", (FWP_E_ALREADY_EXISTS,))
                if not status:
                    added.append(f"filter {key} ({name}, {action})")
            _check(self.dll.FwpmTransactionCommit0(self.handle), "FwpmTransactionCommit0")
        except BaseException:
            self.dll.FwpmTransactionAbort0(self.handle)
            raise
        return added

    def off(self) -> list[str]:
        removed = []
        _check(self.dll.FwpmTransactionBegin0(self.handle, 0), "FwpmTransactionBegin0")
        try:
            for (name, action), key in FILTERS.items():
                status = self.dll.FwpmFilterDeleteByKey0(self.handle, ctypes.byref(GUID.of(key)))
                _check(status, "FwpmFilterDeleteByKey0", (FWP_E_FILTER_NOT_FOUND,))
                if not status:
                    removed.append(f"filter {key} ({name}, {action})")
            status = self.dll.FwpmSubLayerDeleteByKey0(self.handle, ctypes.byref(GUID.of(SUBLAYER)))
            _check(status, "FwpmSubLayerDeleteByKey0", (FWP_E_SUBLAYER_NOT_FOUND,))
            if not status:
                removed.append(f"sublayer {SUBLAYER}")
            _check(self.dll.FwpmTransactionCommit0(self.handle), "FwpmTransactionCommit0")
        except BaseException:
            self.dll.FwpmTransactionAbort0(self.handle)
            raise
        return removed

    def present(self) -> bool:
        out = ctypes.c_void_p()
        status = self.dll.FwpmFilterGetByKey0(self.handle, ctypes.byref(GUID.of(FILTERS[("connect4", "block")])),
                                              ctypes.byref(out))
        if not status:
            self.dll.FwpmFreeMemory0(ctypes.byref(out))
        return not status


# ---------------------------------------------------------------- the Task Scheduler's folders


def _powershell(script: str) -> str:
    import subprocess
    done = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                          capture_output=True, text=True, timeout=120)
    if done.returncode:
        raise OSError(done.returncode, done.stderr.strip()[:500])
    return done.stdout


# Every folder of the Task Scheduler with its descriptor, as JSON.
_FOLDERS = ("$s = New-Object -ComObject Schedule.Service; $s.Connect(); $out = @(); $todo = @($s.GetFolder('\\'));"
            " while ($todo.Count) { $f = $todo[0]; $todo = @($todo | Select-Object -Skip 1);"
            " $out += [pscustomobject]@{path = $f.Path; sddl = $f.GetSecurityDescriptor(4)};"
            " foreach ($c in $f.GetFolders(0)) { $todo += $c } }; ConvertTo-Json @($out) -Compress")


def tasks_on(record: dict) -> list[str]:
    folders = json.loads(_powershell(_FOLDERS) or "[]")
    kept, added = record.setdefault("task_folders", {}), []
    for folder in folders:
        sddl = folder["sddl"]
        if f";;;{GUARD_SID})" in sddl:
            continue
        kept.setdefault(folder["path"], sddl)
        head = sddl[:sddl.find("(")] if "(" in sddl else sddl
        new = head + TASK_FOLDER_DENY + sddl[len(head):]
        path = folder["path"].replace("'", "''")
        _powershell(f"$s = New-Object -ComObject Schedule.Service; $s.Connect(); "
                    f"$s.GetFolder('{path}').SetSecurityDescriptor('{new}', 0)")
        added.append(f"task folder {folder['path']}")
    return added


def tasks_off(record: dict) -> list[str]:
    removed = []
    for path, sddl in list(record.get("task_folders", {}).items()):
        quoted = path.replace("'", "''")
        try:
            _powershell(f"$s = New-Object -ComObject Schedule.Service; $s.Connect(); "
                        f"$s.GetFolder('{quoted}').SetSecurityDescriptor('{sddl}', 0)")
            removed.append(f"task folder {path}")
        except OSError:
            # A folder removed since has nothing left to put back.
            pass
        del record["task_folders"][path]
    return removed


def apply(on: bool, record_path: str, user_sid: str) -> dict:
    """The hardening on or off; the record (what was changed and when) written to `record_path`."""
    try:
        with open(record_path, encoding="utf-8") as f:
            record = json.load(f)
    except (OSError, ValueError):
        record = {}
    engine = Engine()
    try:
        changed = engine.on(user_sid) + tasks_on(record) if on else engine.off() + tasks_off(record)
        record.update(on=on, user=user_sid, at=time.time(), present=engine.present())
    finally:
        engine.close()
    record.setdefault("log", []).append({"at": time.time(), "on": on, "changed": changed})
    os.makedirs(os.path.dirname(record_path), exist_ok=True)
    with open(record_path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=1)
    return record


RECORD = "netguard.json"


def state(desktop) -> dict:
    """What Settings says: whether the hardening is on, as the helper last recorded and Windows still has it."""
    path = os.path.join(desktop, RECORD)
    try:
        with open(path, encoding="utf-8") as f:
            record = json.load(f)
    except (OSError, ValueError):
        record = {}
    error = ""
    if os.path.exists(path + ".error"):
        with open(path + ".error", encoding="utf-8") as f:
            error = f.read()[:300]
    return {"on": bool(record.get("on")), "at": record.get("at"), "error": error}


# How long what Windows' network stack holds is taken as known (`blocking`).
BLOCKING_S = 30.0
_held: list = [-BLOCKING_S, False]


def blocking() -> bool:
    """Whether the block holds now: its filter is in Windows' network stack, whatever Settings or the record says
    (code.py judges code that may reach the network by it)."""
    if sys.platform != "win32":
        return False
    now = time.monotonic()
    if now - _held[0] >= BLOCKING_S:
        try:
            engine = Engine()
            try:
                held = engine.present()
            finally:
                engine.close()
        except OSError:
            held = False
        _held[:] = [now, held]
    return _held[1]


def own_sid() -> str:
    from . import confine
    k32, adv = confine._api()
    token = ctypes.c_void_p()
    confine._ok(adv.OpenProcessToken(k32.GetCurrentProcess(), confine.TOKEN_QUERY, ctypes.byref(token)),
                "OpenProcessToken")
    try:
        return confine._sid_text(confine.SID_AND_ATTRIBUTES.from_buffer(
            confine._token_info(token, confine.TOKEN_USER_CLASS)).Sid)
    finally:
        k32.CloseHandle(token)


class SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint32), ("fMask", ctypes.c_uint32), ("hwnd", ctypes.c_void_p),
                ("lpVerb", ctypes.c_wchar_p), ("lpFile", ctypes.c_wchar_p), ("lpParameters", ctypes.c_wchar_p),
                ("lpDirectory", ctypes.c_wchar_p), ("nShow", ctypes.c_int), ("hInstApp", ctypes.c_void_p),
                ("lpIDList", ctypes.c_void_p), ("lpClass", ctypes.c_wchar_p), ("hkeyClass", ctypes.c_void_p),
                ("dwHotKey", ctypes.c_uint32), ("hIconOrMonitor", ctypes.c_void_p), ("hProcess", ctypes.c_void_p)]


SEE_MASK_NOCLOSEPROCESS, ERROR_CANCELLED = 0x40, 1223


def elevate(on: bool, desktop) -> str:
    """Runs this module as administrator through the system's prompt, for the person's own SID, and waits: "" when
    it is done, "cancelled" when the prompt was declined, "failed" otherwise (its error is in the record's .error)."""
    import subprocess
    record = os.path.join(desktop, RECORD)
    with contextlib.suppress(OSError):
        os.remove(record + ".error")
    words = ["on" if on else "off", record, own_sid()]
    if getattr(sys, "frozen", False):
        program, args = sys.executable, ["netguard", *words]
    else:
        program, args = sys.executable, ["-m", "mibo.shell.netguard", *words]
    info = SHELLEXECUTEINFOW(cbSize=ctypes.sizeof(SHELLEXECUTEINFOW), fMask=SEE_MASK_NOCLOSEPROCESS, lpVerb="runas",
                             lpFile=program, lpParameters=subprocess.list2cmdline(args), nShow=0)
    shell32, k32 = ctypes.WinDLL("shell32", use_last_error=True), ctypes.WinDLL("kernel32")
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFOW)]
    k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    k32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        return "cancelled" if ctypes.get_last_error() == ERROR_CANCELLED else "failed"
    try:
        k32.WaitForSingleObject(info.hProcess, 0xFFFFFFFF)
        code = ctypes.c_uint32()
        k32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
    finally:
        k32.CloseHandle(info.hProcess)
    return "failed" if code.value else ""


def main(argv: list[str], prog: str = "netguard") -> int:
    import argparse
    p = argparse.ArgumentParser(prog=prog)
    p.add_argument("what", choices=("on", "off"))
    p.add_argument("record")
    p.add_argument("sid")
    args = p.parse_args(argv)
    try:
        apply(args.what == "on", args.record, args.sid)
    except OSError as e:
        with open(args.record + ".error", "w", encoding="utf-8") as f:
            f.write(str(e))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
