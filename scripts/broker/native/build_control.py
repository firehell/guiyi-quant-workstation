"""Build the diagnostic against independently verified Mac headers; no downloads."""
import argparse
import hashlib
import platform
import subprocess
from pathlib import Path

HEADERS = {
    "ThostFtdcTraderApi.h": "5cec281d8b273178918c256180e21081bfa6a9aa677fb2cfd465797cc8b1dd8a",
    "ThostFtdcUserApiDataType.h": "8de1bf4c06abd87b21ad0f7ee239286fde0c28c1562e81f85e5fc770a8c8830c",
    "ThostFtdcUserApiStruct.h": "13458040d1a7840e0e9b7ea77acc9251088e591a4e7e8be86fc6c44340d789b5",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--headers", required=True, type=Path)
    parser.add_argument("--library", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        parser.error("Requires macOS ARM64")
    for name, expected in HEADERS.items():
        if hashlib.sha256((args.headers / name).read_bytes()).hexdigest() != expected:
            parser.error("Header identity mismatch")
    # Exactly the installed/pinned SDK library; no alternate binary or loader edits.
    args.output.mkdir(mode=0o700, parents=True, exist_ok=True)
    library = args.library.read_bytes()
    target = args.output / "libthosttraderapi_se.dylib"
    if target.exists() and target.read_bytes() != library:
        parser.error("Output library drift")
    if not target.exists():
        with target.open("xb") as stream:
            stream.write(library)
        target.chmod(0o700)
    root = Path(__file__).resolve().parents[3]
    sdk = subprocess.check_output(["/usr/bin/xcrun", "--show-sdk-path"], text=True).strip()
    flags = ["/Library/Developer/CommandLineTools/usr/bin/clang++", "-std=c++17", "-Wall", "-Wextra",
             "-Wno-unused-parameter", "-Wno-deprecated-declarations", "-isysroot", sdk,
             "-I" + str(args.headers.resolve())]
    subprocess.run(flags + [str(root / "tests/unit/simnow_native/query_control_test.cpp"),
                           "-o", str(args.output / "test")], check=True)
    subprocess.run([str(args.output / "test")], check=True)
    subprocess.run(flags + [str(Path(__file__).with_name("simnow_query_control.cpp")),
                           str(target.resolve()), "-o", str(args.output / "probe")], check=True)
    subprocess.run([str(args.output / "probe"), "--version-check"], check=True)
    print("Header SHA256, native callback tests and SDK load/version verified; no network requests")


if __name__ == "__main__":
    main()
