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


def report_infection(*args, **kwargs):
    from .bridge import report_infection as _r
    return _r(*args, **kwargs)


def submit_to_scheduler(*args, **kwargs):
    from .bridge import submit_to_scheduler as _s
    return _s(*args, **kwargs)


    def dispatch_to_scheduler(*args, **kwargs):
     from .dispatch import dispatch_to_scheduler as _d
    return _d(*args, **kwargs)


def dispatch_from_alert(*args, **kwargs):
    from .dispatch import dispatch_from_alert as _d
    return _d(*args, **kwargs)


    def capture_pre_eradication(*args, **kwargs):
     from .pre_eradication import capture_pre_eradication as _f
    return _f(*args, **kwargs)


def capture_post_eradication(*args, **kwargs):
    from .pre_eradication import capture_post_eradication as _f
    return _f(*args, **kwargs)