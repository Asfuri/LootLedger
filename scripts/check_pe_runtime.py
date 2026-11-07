"""Check the Rust PE's direct/delay imports for extra runtimes and a dynamic CRT."""
import argparse
import json
import os
from pathlib import Path
import struct


def imports(path):
    data = path.read_bytes()
    pe, = struct.unpack_from("<I", data, 0x3C)
    if data[:2] != b"MZ" or data[pe:pe + 4] != b"PE\0\0":
        raise ValueError("Not a Windows PE executable")
    sections, = struct.unpack_from("<H", data, pe + 6)
    opt_size, = struct.unpack_from("<H", data, pe + 20)
    optional = pe + 24
    magic, = struct.unpack_from("<H", data, optional)
    if magic != 0x20B:
        raise ValueError("Expected an x64 PE32+ executable")
    image_base, = struct.unpack_from("<Q", data, optional + 24)
    table = optional + opt_size
    headers_size, = struct.unpack_from("<I", data, optional + 60)

    def offset(rva):
        if rva < headers_size:
            return rva
        for n in range(sections):
            virtual_size, address, raw_size, raw = struct.unpack_from("<IIII", data, table + n * 40 + 8)
            if address <= rva < address + max(raw_size, virtual_size):
                return raw + rva - address
        raise ValueError("Import RVA is outside the PE sections")

    def string(rva):
        start = offset(rva)
        end = data.index(b"\0", start)
        return data[start:end].decode("ascii")

    result = set()
    import_rva, = struct.unpack_from("<I", data, optional + 112 + 8)
    if import_rva:
        start = offset(import_rva)
        for n in range(4096):
            descriptor = struct.unpack_from("<IIIII", data, start + n * 20)
            if not any(descriptor):
                break
            result.add(string(descriptor[3]).lower())
        else:
            raise ValueError("Import descriptors have no terminator")
    delay_rva, = struct.unpack_from("<I", data, optional + 112 + 13 * 8)
    if delay_rva:
        start = offset(delay_rva)
        for n in range(4096):
            descriptor = struct.unpack_from("<IIIIIIII", data, start + n * 32)
            if not any(descriptor):
                break
            result.add(string(descriptor[1] if descriptor[0] & 1 else descriptor[1] - image_base).lower())
        else:
            raise ValueError("Delay imports have no terminator")
    return sorted(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("exe", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    dlls = imports(args.exe)
    forbidden = ("vcruntime", "msvcp", "ucrtbase", "api-ms-win-crt", "python", "qt5", "qt6",
                 "coreclr", "hostfxr", "webview", "node", "libgcc", "libstd")
    bad = [dll for dll in dlls if any(part in dll for part in forbidden)]
    system = Path(os.environ["SystemRoot"]) / "System32"
    extra = [dll for dll in dlls if not dll.startswith(("api-ms-", "ext-ms-")) and not (system / dll).is_file()]
    report = {"exe_bytes": args.exe.stat().st_size, "direct_and_delay_imports": dlls,
              "forbidden_runtime_imports": bad, "non_system_imports": extra, "passed": not bad and not extra,
              "note": "Direct/delay PE imports only; not proof that every runtime code path avoids LoadLibrary."}
    text = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
