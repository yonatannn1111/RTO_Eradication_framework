"""
Forensics package — lazy imports for snap7-dependent modules.
"""


def capture(*args, **kwargs):
    from .snapshot import capture as _capture
    return _capture(*args, **kwargs)


def restore(*args, **kwargs):
    from .restore import restore as _restore
    return _restore(*args, **kwargs)


def validate(*args, **kwargs):
    from .restore import validate as _validate
    return _validate(*args, **kwargs)


def restore_with_retry(*args, **kwargs):
    from .restore import restore_with_retry as _r
    return _r(*args, **kwargs)


def compare(*args, **kwargs):
    from .compare import compare_snapshots as _cmp
    return _cmp(*args, **kwargs)


def export_json(*args, **kwargs):
    from .compare import export_json as _ej
    return _ej(*args, **kwargs)


def export_pdf(*args, **kwargs):
    from .compare import export_pdf as _ep
    return _ep(*args, **kwargs)


from .diff import diff   # no external deps

# Expose the exception class (lightweight — no snap7 import needed)
def __getattr__(name):
    if name == "RestoreFailedError":
        from .restore import RestoreFailedError
        return RestoreFailedError
    raise AttributeError(name)


__all__ = [
    "capture", "diff", "restore", "validate",
    "restore_with_retry", "RestoreFailedError",
    "compare", "export_json", "export_pdf",
]