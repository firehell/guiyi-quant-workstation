"""Stdlib-only child gate: parent EOF exits even before application imports."""
import os
import signal
import sys
import threading


def main():
    try:
        descriptor = int(sys.argv[sys.argv.index('--parent-fd') + 1])
        gate = threading.Event()
        def watch():
            try:
                if os.read(descriptor, 1) != b'G':
                    os._exit(70)
                gate.set()
                while os.read(descriptor, 1):
                    pass
            finally:
                os._exit(70)
        signal.signal(signal.SIGALRM, lambda *_: os._exit(71))
        signal.setitimer(signal.ITIMER_REAL, 120)
        threading.Thread(target=watch, daemon=True).start()
        if not gate.wait(10):
            return 72
        os.environ['GUIYI_HOME_CHILD_GATED'] = '1'
        from app.market_data.newow.home_recovery import main as compute
        return compute(['compute', *sys.argv[1:]])
    except Exception:
        return 73


if __name__ == '__main__':
    raise SystemExit(main())
