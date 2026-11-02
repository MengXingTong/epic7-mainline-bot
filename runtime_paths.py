"""Resolve private runtime paths independently of the source checkout."""
import os
from pathlib import Path
CODE_ROOT=Path(__file__).resolve().parent

def data_root():
    value=os.environ.get('EPIC7_DATA_DIR')
    return Path(value).expanduser().resolve() if value else CODE_ROOT

def config_path():
    value=os.environ.get('EPIC7_CONFIG_PATH')
    return Path(value).expanduser().resolve() if value else data_root()/'config.json'


from contextlib import contextmanager

@contextmanager
def exclusive_profile(root):
    """Use the same supervisor/worker locks as both transports; no second writer."""
    import msvcrt
    handles=[]
    def release():
        while handles:
            handle=handles.pop()
            try:handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            finally:handle.close()
    try:
        for name in ('supervisor.lock','worker.lock'):
            handle=(Path(root)/name).open('a+b')
            if handle.seek(0,os.SEEK_END)==0:handle.write(b'0');handle.flush()
            handle.seek(0)
            try:msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            except OSError:
                handle.close();raise RuntimeError('A supervisor/worker already owns this profile; no PC input or state write')
            handles.append(handle)
        yield release
    finally:release()
