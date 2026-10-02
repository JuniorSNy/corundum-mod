# SPDX-License-Identifier: BSD-2-Clause
"""Bounded reproduction of the local asyncio child-exit hang, without RTL."""
import argparse
import asyncio
import faulthandler
from pathlib import Path
import subprocess
import sys


def worker(backend, count):
    faulthandler.dump_traceback_later(5)
    async def run():
        process = await asyncio.create_subprocess_exec(
            'true', stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        await process.communicate()
        assert process.returncode == 0
    for index in range(count):
        if backend == 'async':
            asyncio.run(run())
        else:
            subprocess.run(['true'], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           check=True, timeout=2)
        print(f'{backend}: child {index+1} reaped', flush=True)
    faulthandler.cancel_dump_traceback_later()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', choices=['async', 'sync'], default='async')
    parser.add_argument('--count', type=int, default=100)
    parser.add_argument('--timeout', type=float, default=10)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        worker(args.backend, args.count)
    else:
        command = [sys.executable, str(Path(__file__).resolve()), '--worker',
                   '--backend', args.backend, '--count', str(args.count)]
        try:
            result = subprocess.run(command, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, timeout=args.timeout)
        except subprocess.TimeoutExpired as exc:
            print((exc.stdout or b'').decode(errors='replace'))
            print('TIMEOUT: child supervision did not complete')
            sys.exit(1)
        print(result.stdout.decode(errors='replace'))
        sys.exit(result.returncode)
